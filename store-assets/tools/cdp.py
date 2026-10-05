"""標準ライブラリだけで書いた、最小限の Chrome DevTools Protocol クライアント。

- RFC 6455 の WebSocket クライアント（マスク付きフレーム、分割メッセージ、16/64 bit 長、
  ping/pong、close ハンドシェイク）
- --remote-debugging-pipe での接続（CDP の Extensions.loadUnpacked はこの接続でしか使えない）
    * macOS / Linux: os.pipe() を子プロセスの fd 3（Chrome が読む）/ fd 4（Chrome が書く）に dup2 する
    * Windows: CreateProcessW の STARTUPINFO.lpReserved2 で CRT の fd 3 / 4 を引き継ぐ
- フラットセッション（Target.attachToTarget flatten=True）の補助
- Fetch ドメインでリクエストを横取りし、ローカルのファイルを返す補助（MockSite / RequestInterceptor）。
  再現ページ（tools/mock/）を https://trello.com/... として表示し、それ以外の通信はすべて失敗させる。

ギガひろ（Giga-Hiro/store-assets/tools/cdp.py）を移植し、POSIX のパイプ接続・ブラウザの自動検出・
リクエストの横取りを加えたもの。Python 3.9 以上で動く（numpy などの外部ライブラリは不要）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlparse

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CDPError(Exception):
    pass


class ConnectionClosed(Exception):
    pass


# ---------------------------------------------------------------------------
# ブラウザの場所（プラットフォームごとに自動判定。--browser や環境変数 CHROME_PATH で上書き）
# ---------------------------------------------------------------------------
def chrome_candidates() -> list[str]:
    if sys.platform == "win32":
        out = []
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        out.insert(0, r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        return out
    if sys.platform == "darwin":
        app = os.path.join("Google Chrome.app", "Contents", "MacOS", "Google Chrome")
        return [os.path.join("/Applications", app), os.path.expanduser(os.path.join("~/Applications", app))]
    out = []
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            out.append(found)
    return out or ["/usr/bin/google-chrome"]


def find_chrome(override: str | None = None) -> str:
    """Chrome の実行ファイルを返す。override → 環境変数 CHROME_PATH → 既定の場所 の順。"""
    for cand in (override, os.environ.get("CHROME_PATH")):
        if cand:
            return cand
    cands = chrome_candidates()
    for cand in cands:
        if os.path.exists(cand):
            return cand
    return cands[0]


# ---------------------------------------------------------------------------
# WebSocket (RFC 6455) client
# ---------------------------------------------------------------------------
class WebSocket:
    OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA

    def __init__(self, url: str, connect_timeout: float = 10.0, max_frame: int = 1 << 20):
        u = urlparse(url)
        if u.scheme != "ws":
            raise ValueError("only ws:// is supported: " + url)
        host = u.hostname or "127.0.0.1"
        port = u.port or 80
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        self.max_frame = max_frame
        self._send_lock = threading.Lock()
        self._buf = bytearray()
        self.sock = socket.create_connection((host, port), timeout=connect_timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionClosed("handshake: connection closed")
            self._buf += chunk
        head, _, rest = bytes(self._buf).partition(b"\r\n\r\n")
        self._buf = bytearray(rest)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise ConnectionClosed("handshake failed: " + lines[0])
        headers = {}
        for line in lines[1:]:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()
        expect = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if headers.get("sec-websocket-accept") != expect:
            raise ConnectionClosed("bad Sec-WebSocket-Accept")
        self.sock.settimeout(None)
        self.closed = False

    # -- low level ---------------------------------------------------------
    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self._buf)))
            if not chunk:
                raise ConnectionClosed("socket closed")
            self._buf += chunk
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    @staticmethod
    def _mask(payload: bytes, mask: bytes) -> bytes:
        n = len(payload)
        if n == 0:
            return b""
        m = (mask * (n // 4 + 1))[:n]
        return (int.from_bytes(payload, "big") ^ int.from_bytes(m, "big")).to_bytes(n, "big")

    def _send_frame(self, opcode: int, payload: bytes, fin: bool = True) -> None:
        b0 = (0x80 if fin else 0x00) | opcode
        n = len(payload)
        if n < 126:
            header = struct.pack("!BB", b0, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", b0, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", b0, 0x80 | 127, n)
        mask = os.urandom(4)
        data = header + mask + self._mask(payload, mask)
        with self._send_lock:
            self.sock.sendall(data)

    def _recv_frame(self):
        b0, b1 = self._recv_exact(2)
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        n = b1 & 0x7F
        if n == 126:
            (n,) = struct.unpack("!H", self._recv_exact(2))
        elif n == 127:
            (n,) = struct.unpack("!Q", self._recv_exact(8))
        mask = self._recv_exact(4) if masked else None
        payload = self._recv_exact(n) if n else b""
        if mask:
            payload = self._mask(payload, mask)
        return fin, opcode, payload

    # -- public ------------------------------------------------------------
    def send_text(self, text: str) -> None:
        data = text.encode("utf-8")
        if len(data) <= self.max_frame:
            self._send_frame(self.OP_TEXT, data)
            return
        # 分割メッセージ: 最初は TEXT(fin=0)、続きは CONT
        chunks = [data[i:i + self.max_frame] for i in range(0, len(data), self.max_frame)]
        for i, chunk in enumerate(chunks):
            op = self.OP_TEXT if i == 0 else self.OP_CONT
            self._send_frame(op, chunk, fin=(i == len(chunks) - 1))

    def recv(self) -> str:
        parts = []
        msg_op = None
        while True:
            fin, op, payload = self._recv_frame()
            if op == self.OP_PING:
                self._send_frame(self.OP_PONG, payload)
                continue
            if op == self.OP_PONG:
                continue
            if op == self.OP_CLOSE:
                try:
                    self._send_frame(self.OP_CLOSE, payload[:2])
                except OSError:
                    pass
                self.closed = True
                raise ConnectionClosed("close frame received")
            if op in (self.OP_TEXT, self.OP_BINARY):
                parts = [payload]
                msg_op = op
            elif op == self.OP_CONT:
                parts.append(payload)
            if fin and msg_op is not None:
                data = b"".join(parts)
                return data.decode("utf-8") if msg_op == self.OP_TEXT else data.decode("latin-1")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self._send_frame(self.OP_CLOSE, struct.pack("!H", 1000))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------
class WebSocketTransport:
    def __init__(self, url: str):
        self.ws = WebSocket(url)

    def send(self, text: str) -> None:
        self.ws.send_text(text)

    def recv(self) -> str:
        return self.ws.recv()

    def close(self) -> None:
        self.ws.close()


class PipeTransport:
    """--remote-debugging-pipe: NUL 区切りの JSON を 2 本の OS パイプでやり取りする。"""

    def __init__(self, read_file, write_file):
        self.r = read_file
        self.w = write_file
        self._buf = bytearray()
        self._lock = threading.Lock()

    def send(self, text: str) -> None:
        with self._lock:
            self.w.write(text.encode("utf-8") + b"\0")
            self.w.flush()

    def recv(self) -> str:
        while True:
            i = self._buf.find(b"\0")
            if i >= 0:
                msg = bytes(self._buf[:i])
                del self._buf[:i + 1]
                return msg.decode("utf-8")
            chunk = self.r.read(65536)
            if not chunk:
                raise ConnectionClosed("pipe closed")
            self._buf += chunk

    def close(self) -> None:
        for f in (self.w, self.r):
            try:
                f.close()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# CDP client
# ---------------------------------------------------------------------------
class CDP:
    def __init__(self, transport):
        self.t = transport
        self._id = 0
        self._id_lock = threading.Lock()
        self._pending: dict = {}
        self._cond = threading.Condition()
        self.events: list = []
        # subscribe() で登録した (メソッド名の集合, キュー)。イベントを別スレッドで処理したいとき用
        self._subscribers: list = []
        self.closed = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self):
        try:
            while True:
                msg = json.loads(self.t.recv())
                with self._cond:
                    if "id" in msg and msg["id"] in self._pending:
                        self._pending[msg["id"]][1] = msg
                    else:
                        self.events.append(msg)
                        for methods, q in self._subscribers:
                            if msg.get("method") in methods:
                                q.put(msg)
                    self._cond.notify_all()
        except (ConnectionClosed, OSError, ValueError):
            pass
        finally:
            with self._cond:
                self.closed = True
                for _, q in self._subscribers:
                    q.put(None)
                self._cond.notify_all()

    def subscribe(self, methods) -> queue.Queue:
        """指定したメソッドのイベントを受け取るキューを返す。接続が切れると None が入る。

        読み取りスレッドの中で send() を呼ぶと応答を待てずに止まるので、
        イベントに応答する処理（Fetch.requestPaused など）はこのキューを別スレッドで読む。
        """
        q: queue.Queue = queue.Queue()
        with self._cond:
            self._subscribers.append((set(methods), q))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._cond:
            self._subscribers = [(m, x) for (m, x) in self._subscribers if x is not q]
        q.put(None)

    def send(self, method: str, params: dict | None = None, session_id: str | None = None,
             timeout: float = 60.0) -> dict:
        with self._id_lock:
            self._id += 1
            mid = self._id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        with self._cond:
            if self.closed:
                raise ConnectionClosed(f"connection closed before {method}")
            self._pending[mid] = [None, None]
        self.t.send(json.dumps(msg))
        deadline = time.time() + timeout
        with self._cond:
            while self._pending[mid][1] is None:
                if self.closed:
                    del self._pending[mid]
                    raise ConnectionClosed(f"connection closed while waiting for {method}")
                left = deadline - time.time()
                if left <= 0:
                    del self._pending[mid]
                    raise TimeoutError(f"timeout waiting for {method}")
                self._cond.wait(left)
            resp = self._pending.pop(mid)[1]
        if "error" in resp:
            raise CDPError(f"{method}: {resp['error']}")
        return resp.get("result", {})

    def mark(self) -> int:
        with self._cond:
            return len(self.events)

    def wait_event(self, method: str, session_id: str | None = None, predicate=None,
                   since: int = 0, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        idx = since
        with self._cond:
            while True:
                while idx < len(self.events):
                    ev = self.events[idx]
                    idx += 1
                    if ev.get("method") != method:
                        continue
                    if session_id and ev.get("sessionId") != session_id:
                        continue
                    if predicate and not predicate(ev.get("params", {})):
                        continue
                    return ev.get("params", {})
                if self.closed:
                    raise ConnectionClosed(f"closed while waiting for event {method}")
                left = deadline - time.time()
                if left <= 0:
                    raise TimeoutError(f"timeout waiting for event {method}")
                self._cond.wait(left)

    def close(self):
        self.t.close()


class Session:
    """1 つのターゲット（ページ）に付けたフラットセッション。"""

    def __init__(self, cdp: CDP, target_id: str, session_id: str):
        self.cdp = cdp
        self.target_id = target_id
        self.session_id = session_id

    def send(self, method, params=None, timeout=60.0):
        return self.cdp.send(method, params, session_id=self.session_id, timeout=timeout)

    def mark(self):
        return self.cdp.mark()

    def wait_event(self, method, predicate=None, since=0, timeout=30.0):
        return self.cdp.wait_event(method, self.session_id, predicate, since, timeout)

    def events_since(self, since: int, method: str | None = None) -> list:
        return [ev for ev in self.cdp.events[since:]
                if ev.get("sessionId") == self.session_id and (method is None or ev.get("method") == method)]

    def evaluate(self, expression: str, context_id: int | None = None, await_promise: bool = True,
                 timeout: float = 60.0):
        params = {"expression": expression, "returnByValue": True, "awaitPromise": await_promise}
        if context_id is not None:
            params["contextId"] = context_id
        r = self.send("Runtime.evaluate", params, timeout=timeout)
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            desc = d.get("exception", {}).get("description") or d.get("text")
            raise CDPError(f"JS exception: {desc}")
        return r.get("result", {}).get("value")

    def navigate(self, url: str, timeout: float = 60.0):
        m = self.mark()
        r = self.send("Page.navigate", {"url": url})
        if r.get("errorText"):
            raise CDPError(f"navigate {url}: {r['errorText']}")
        self.wait_event("Page.loadEventFired", since=m, timeout=timeout)
        return r

    def wait_for(self, expression: str, timeout: float = 20.0, interval: float = 0.1,
                 context_id: int | None = None):
        """JS の式が truthy になるまで待ち、その値を返す。"""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = self.evaluate(expression, context_id=context_id)
            except CDPError:
                last = None
            if last:
                return last
            time.sleep(interval)
        raise TimeoutError(f"condition not met: {expression[:160]}")

    def click(self, x: float, y: float, button: str = "left"):
        """ビューポート座標 (CSS px) を本物のマウス操作としてクリックする。"""
        base = {"x": x, "y": y, "button": button, "clickCount": 1}
        self.send("Input.dispatchMouseEvent", dict(base, type="mouseMoved", button="none", clickCount=0))
        self.send("Input.dispatchMouseEvent", dict(base, type="mousePressed"))
        self.send("Input.dispatchMouseEvent", dict(base, type="mouseReleased"))

    def screenshot(self, path: str, clip: dict | None = None):
        params = {"format": "png", "captureBeyondViewport": False}
        if clip:
            params["clip"] = dict(clip, scale=clip.get("scale", 1))
            params["captureBeyondViewport"] = True
        r = self.send("Page.captureScreenshot", params, timeout=120)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        return path


# ---------------------------------------------------------------------------
# パイプ付きでブラウザを起動する
# ---------------------------------------------------------------------------
def _spawn_with_pipes_posix(argv: list[str]):
    """子プロセスの fd 3（Chrome が読む）と fd 4（Chrome が書く）にパイプをつないで起動する。"""
    import fcntl

    p2c_r, p2c_w = os.pipe()   # 親 → Chrome（fd 3）
    c2p_r, c2p_w = os.pipe()   # Chrome（fd 4）→ 親

    def preexec():
        # いったん 10 番以降に複製してから 3 / 4 に置く（元の番号が 3 / 4 と重なっても壊れないように）。
        # dup2 で作った fd は close-on-exec が外れるので、exec 後の Chrome に引き継がれる。
        a = fcntl.fcntl(p2c_r, fcntl.F_DUPFD, 10)
        b = fcntl.fcntl(c2p_w, fcntl.F_DUPFD, 10)
        os.dup2(a, 3)
        os.dup2(b, 4)
        os.close(a)
        os.close(b)

    # close_fds=False でも、Python が開く fd は既定で引き継がれない（PEP 446）ので、
    # Chrome に渡るのは標準入出力と上で置いた fd 3 / 4 だけ。
    proc = subprocess.Popen(argv, preexec_fn=preexec, close_fds=False,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    os.close(p2c_r)
    os.close(c2p_w)
    return proc, os.fdopen(c2p_r, "rb", buffering=0), os.fdopen(p2c_w, "wb", buffering=0)


def _spawn_with_pipes_windows(argv: list[str]):
    """CreateProcessW で CRT の fd 3（子が読む）と fd 4（子が書く）を引き継いで起動する。"""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", wintypes.LPVOID),
                    ("bInheritHandle", wintypes.BOOL)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                    ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                    ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    k32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
                               ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD]
    k32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                   wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                   ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]

    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    child_r, parent_w = wintypes.HANDLE(), wintypes.HANDLE()   # parent -> child (fd 3)
    parent_r, child_w = wintypes.HANDLE(), wintypes.HANDLE()   # child -> parent (fd 4)
    if not k32.CreatePipe(ctypes.byref(child_r), ctypes.byref(parent_w), ctypes.byref(sa), 1 << 20):
        raise ctypes.WinError(ctypes.get_last_error())
    if not k32.CreatePipe(ctypes.byref(parent_r), ctypes.byref(child_w), ctypes.byref(sa), 1 << 20):
        raise ctypes.WinError(ctypes.get_last_error())
    HANDLE_FLAG_INHERIT = 1
    k32.SetHandleInformation(parent_w, HANDLE_FLAG_INHERIT, 0)
    k32.SetHandleInformation(parent_r, HANDLE_FLAG_INHERIT, 0)

    # MS C ランタイムが使う lpReserved2 の形式: int count; BYTE flags[count]; HANDLE h[count]
    FOPEN, FPIPE = 0x01, 0x08
    INVALID = ctypes.c_void_p(-1).value
    count = 5
    flags = bytes([0, 0, 0, FOPEN | FPIPE, FOPEN | FPIPE])
    handles = [INVALID, INVALID, INVALID, child_r.value, child_w.value]
    blob = struct.pack("<i", count) + flags + b"".join(struct.pack("<Q", h) for h in handles)
    blob_buf = ctypes.create_string_buffer(blob, len(blob))

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.cbReserved2 = len(blob)
    si.lpReserved2 = ctypes.cast(blob_buf, ctypes.c_void_p)
    pi = PROCESS_INFORMATION()
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    CREATE_NO_WINDOW = 0x08000000
    ok = k32.CreateProcessW(argv[0], cmdline, None, None, True, CREATE_NO_WINDOW, None, None,
                            ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    k32.CloseHandle(pi.hThread)
    k32.CloseHandle(child_r)
    k32.CloseHandle(child_w)
    wfd = msvcrt.open_osfhandle(parent_w.value, os.O_WRONLY | os.O_BINARY)
    rfd = msvcrt.open_osfhandle(parent_r.value, os.O_RDONLY | os.O_BINARY)
    return pi.dwProcessId, pi.hProcess, os.fdopen(rfd, "rb", buffering=0), os.fdopen(wfd, "wb", buffering=0)


# 撮影中に Chrome 自身が裏で通信しないようにするための引数。
# --host-resolver-rules で名前解決をすべて失敗させるので、Fetch で横取りしなかった通信は外へ出ない。
OFFLINE_ARGS = [
    "--host-resolver-rules=MAP * ~NOTFOUND",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-domain-reliability",
    "--disable-client-side-phishing-detection",
    "--no-pings",
    "--metrics-recording-only",
    "--safebrowsing-disable-auto-update",
    "--disable-features=Translate,OptimizationHints,MediaRouter,AutofillServerCommunication,"
    "CertificateTransparencyComponentUpdater,InterestFeedContentSuggestions",
]


class Browser:
    def __init__(self, exe: str | None, user_data_dir: str, extra_args: list[str] | None = None,
                 headless: bool = True, pipe: bool = False, offline: bool = False,
                 startup_timeout: float = 30.0, lang: str = "ja"):
        self.exe = find_chrome(exe)
        self.user_data_dir = os.path.abspath(user_data_dir)
        os.makedirs(self.user_data_dir, exist_ok=True)
        argv = [self.exe, f"--user-data-dir={self.user_data_dir}", "--no-first-run",
                "--no-default-browser-check", "--disable-background-networking",
                "--disable-component-update", "--mute-audio", f"--lang={lang}",
                "--window-size=1280,800"]
        if sys.platform == "darwin":
            argv.append("--use-mock-keychain")   # キーチェーンの確認ダイアログを出さない
        if offline:
            argv += OFFLINE_ARGS
        if headless:
            argv.append("--headless=new")
        argv += extra_args or []
        self.pid = None
        self._hprocess = None
        self.proc = None
        if pipe:
            argv.append("--remote-debugging-pipe")
            argv.append("about:blank")
            if sys.platform == "win32":
                self.pid, self._hprocess, rf, wf = _spawn_with_pipes_windows(argv)
            else:
                self.proc, rf, wf = _spawn_with_pipes_posix(argv)
                self.pid = self.proc.pid
            self.cdp = CDP(PipeTransport(rf, wf))
        else:
            port_file = os.path.join(self.user_data_dir, "DevToolsActivePort")
            if os.path.exists(port_file):
                os.remove(port_file)
            argv.append("--remote-debugging-port=0")
            argv.append("about:blank")
            self.proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.pid = self.proc.pid
            deadline = time.time() + startup_timeout
            ws_url = None
            while time.time() < deadline:
                if os.path.exists(port_file):
                    try:
                        with open(port_file, encoding="utf-8") as f:
                            lines = f.read().split()
                        if len(lines) >= 2:
                            ws_url = f"ws://127.0.0.1:{lines[0]}{lines[1]}"
                            break
                    except OSError:
                        pass
                if self.proc.poll() is not None:
                    raise RuntimeError(f"browser exited early ({self.proc.returncode})")
                time.sleep(0.2)
            if not ws_url:
                self.kill()
                raise TimeoutError("DevToolsActivePort not found")
            self.cdp = CDP(WebSocketTransport(ws_url))
        self.argv = argv
        # パイプ接続では起動直後の 1 通目が遅れることがあるので、応答が返るまで待つ
        deadline = time.time() + startup_timeout
        while True:
            try:
                self.version = self.cdp.send("Browser.getVersion", timeout=5)
                break
            except TimeoutError:
                if time.time() > deadline or not self._alive():
                    self.kill()
                    raise

    def send(self, method, params=None, timeout=60.0):
        return self.cdp.send(method, params, timeout=timeout)

    def attach(self, target_id: str) -> Session:
        sid = self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
        return Session(self.cdp, target_id, sid)

    def new_page(self, url: str = "about:blank", width: int = 1280, height: int = 800,
                 dpr: float = 2, browser_context_id: str | None = None, before_navigate=None) -> Session:
        """新しいタブを開く。before_navigate(session) は Fetch.enable などを最初の読み込みの前に行うため。"""
        p = {"url": "about:blank"}
        if browser_context_id:
            p["browserContextId"] = browser_context_id
        tid = self.send("Target.createTarget", p)["targetId"]
        s = self.attach(tid)
        s.send("Page.enable")
        s.send("Runtime.enable")
        s.send("Emulation.setDeviceMetricsOverride",
               {"width": width, "height": height, "deviceScaleFactor": dpr, "mobile": False})
        if before_navigate:
            before_navigate(s)
        if url != "about:blank":
            s.navigate(url)
        return s

    def close_page(self, s: Session):
        try:
            self.send("Target.closeTarget", {"targetId": s.target_id}, timeout=10)
        except (CDPError, TimeoutError, ConnectionClosed):
            pass

    def _alive(self) -> bool:
        if self.proc is not None:
            return self.proc.poll() is None
        if self._hprocess is not None:
            import ctypes
            return ctypes.windll.kernel32.WaitForSingleObject(self._hprocess, 0) != 0
        return False

    def kill(self):
        if self.pid and sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif self.proc is not None:
            self.proc.kill()

    def close(self, timeout: float = 10.0):
        try:
            self.cdp.send("Browser.close", timeout=5)
        except Exception:
            pass
        deadline = time.time() + timeout
        while time.time() < deadline and self._alive():
            time.sleep(0.2)
        if self._alive():
            self.kill()
        try:
            self.cdp.close()
        except Exception:
            pass
        if self._hprocess is not None:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self._hprocess)
            self._hprocess = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def kill_leftovers(user_data_dir: str, image_names=("chrome.exe", "msedge.exe")) -> int:
    """user_data_dir をコマンドラインに含むブラウザのプロセスが残っていたら終了させる。"""
    needle = os.path.abspath(user_data_dir)
    if sys.platform != "win32":
        try:
            out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
        except OSError:
            return 0
        killed = 0
        for line in out.splitlines():
            pid, _, cmd = line.strip().partition(" ")
            if f"--user-data-dir={needle}" in cmd and pid.isdigit() and int(pid) != os.getpid():
                try:
                    os.kill(int(pid), 9)
                    killed += 1
                except OSError:
                    pass
        return killed
    needle = needle.replace("'", "''")
    names = ",".join(f"'{n}'" for n in image_names)
    ps = (
        f"$n=@({names}); $k=0; Get-CimInstance Win32_Process | "
        "Where-Object { $n -contains $_.Name -and $_.CommandLine -and "
        f"$_.CommandLine.Contains('{needle}') }} | ForEach-Object {{ "
        "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $k++ }; $k"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    try:
        return int((r.stdout or "0").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


# ---------------------------------------------------------------------------
# リクエストの横取り（Fetch ドメイン）
# ---------------------------------------------------------------------------
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}

# 再現ページの既定の道順。trello.com と同じ URL の形でモックの HTML を返す。
TRELLO_ROUTES = [
    (r"^/b/[^/]+(/.*)?$", "board.html"),
    (r"^/c/[^/]+(/.*)?$", "card.html"),
]


class MockSite:
    """origin（既定は https://trello.com）の URL を、root 以下のローカルファイルに対応付ける。

    - routes の正規表現に合うパス → その HTML（例: /b/<id>/<slug> → board.html、/c/<id>/<slug> → card.html）
    - static_prefix 以下（既定 /__mock/）→ root 以下の同じ名前のファイル（拡張子から Content-Type を決める）
    - 同じ origin のそれ以外のパス → ローカルで 404 を返す（外へは出さない）
    - 別の origin → None（呼び出し側で失敗させる）
    """

    def __init__(self, root: str, origin: str = "https://trello.com", routes=None,
                 static_prefix: str = "/__mock/"):
        self.root = os.path.abspath(root)
        self.origin = origin.rstrip("/")
        self.routes = [(re.compile(p), f) for p, f in (routes or TRELLO_ROUTES)]
        self.static_prefix = static_prefix

    def _file(self, rel: str):
        path = os.path.abspath(os.path.join(self.root, rel))
        if not (path == self.root or path.startswith(self.root + os.sep)) or not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            body = f.read()
        ext = os.path.splitext(path)[1].lower()
        ctype = CONTENT_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
        return 200, ctype, body, rel

    def resolve_path(self, path: str):
        """パス（クエリなし）→ (status, content_type, body, ローカルの相対パス or None)。"""
        path = unquote(path or "/")
        if path.startswith(self.static_prefix):
            hit = self._file(path[len(self.static_prefix):])
            if hit:
                return hit
        else:
            for pattern, rel in self.routes:
                if pattern.match(path):
                    hit = self._file(rel)
                    if hit:
                        return hit
        return 404, "text/plain; charset=utf-8", b"not found (mock)", None

    def resolve(self, url: str):
        u = urlparse(url)
        if f"{u.scheme}://{u.netloc}".lower() != self.origin.lower():
            return None
        return self.resolve_path(u.path)


class RequestInterceptor:
    """Fetch.requestPaused に応答するスレッド。

    attach(session) したタブのリクエストをすべて一時停止させ、
      - MockSite が知っている URL → Fetch.fulfillRequest でローカルのファイルを返す
      - http / https / ws などそれ以外 → Fetch.failRequest（BlockedByClient）で失敗させ、記録する
      - chrome-extension: / data: など、もともとネットワークを使わないもの → そのまま続行
    ネットワークへは一切出さない。
    """

    LOCAL_SCHEMES = ("chrome-extension", "data", "blob", "about", "chrome", "devtools", "file")

    def __init__(self, cdp: CDP, site: MockSite):
        self.cdp = cdp
        self.site = site
        self.served: list = []
        self.not_found: list = []
        self.blocked: list = []
        self.continued: list = []
        self.errors: list = []
        self._lock = threading.Lock()
        self._q = cdp.subscribe({"Fetch.requestPaused"})
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def attach(self, session: Session):
        session.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})

    def stop(self):
        self.cdp.unsubscribe(self._q)

    def _run(self):
        while True:
            ev = self._q.get()
            if ev is None:
                return
            try:
                self._handle(ev)
            except (CDPError, ConnectionClosed, TimeoutError) as e:
                with self._lock:
                    self.errors.append(str(e))

    def _handle(self, ev: dict):
        p = ev.get("params", {})
        sid = ev.get("sessionId")
        rid = p["requestId"]
        req = p.get("request", {})
        url = req.get("url", "")
        rtype = p.get("resourceType")
        scheme = urlparse(url).scheme.lower()
        if scheme in self.LOCAL_SCHEMES:
            self.cdp.send("Fetch.continueRequest", {"requestId": rid}, session_id=sid)
            with self._lock:
                self.continued.append({"url": url[:200], "type": rtype})
            return
        hit = self.site.resolve(url) if req.get("method", "GET") in ("GET", "HEAD") else None
        if hit is None:
            self.cdp.send("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"},
                          session_id=sid)
            with self._lock:
                self.blocked.append({"url": url, "type": rtype, "method": req.get("method")})
            return
        status, ctype, body, rel = hit
        headers = [{"name": "Content-Type", "value": ctype},
                   {"name": "Cache-Control", "value": "no-store"}]
        self.cdp.send("Fetch.fulfillRequest", {
            "requestId": rid, "responseCode": status, "responseHeaders": headers,
            "body": base64.b64encode(body).decode("ascii")}, session_id=sid)
        with self._lock:
            (self.served if status == 200 else self.not_found).append(
                {"url": url, "type": rtype, "status": status, "file": rel})

    def summary(self) -> dict:
        with self._lock:
            files: dict = {}
            for r in self.served:
                files[r["file"]] = files.get(r["file"], 0) + 1
            return {
                "served": len(self.served),
                "served_files": files,
                "not_found_local": len(self.not_found),
                "not_found_urls": sorted({r["url"] for r in self.not_found}),
                "blocked": len(self.blocked),
                "blocked_urls": sorted({r["url"] for r in self.blocked}),
                "continued_local_scheme": len(self.continued),
                "errors": list(self.errors),
            }
