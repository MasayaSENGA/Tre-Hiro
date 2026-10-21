"""トレひろの Chrome ウェブストア提出用 ZIP を作り、中身を検証するツール。

使い方（リポジトリのルートで実行。macOS / Windows 共通。標準ライブラリだけで動きます）:

    python3 store-assets/tools/package.py                  # dist/tre-hiro-<version>.zip を作る
    python3 store-assets/tools/package.py --out build      # build/tre-hiro-<version>.zip を作る
    python3 store-assets/tools/package.py --out ../x.zip   # ファイル名まで指定する

    Windows では python3 の代わりに py または python を使います。

ZIP に入れるのは、下の ALLOWLIST に並べた拡張機能のファイルだけです（manifest.json は ZIP のルート）。
.claude/、.git/、README.md、store-assets/ などは入りません。ファイルを増やしたときは ALLOWLIST に追加してください。

同じ内容なら毎回同じ ZIP になるよう、エントリーの順序（manifest.json が先頭、残りはパスの昇順）、
日時（FIXED_DATE_TIME）、属性を固定しています。

作った後に ZIP を開き直して、次を検証します。1つでも失敗したら ZIP を削除し、終了コード 1 で終わります。

- ZIP が壊れていない（CRC）。中身が ALLOWLIST と完全に一致する（余分なファイル・足りないファイルがない）
- 各ファイルの中身がリポジトリのファイルと同じ
- manifest.json がルートにあり、JSON として正しい（キーの重複・BOM なし）
- version が正しい形式で、ファイル名の version と一致する
- name が 75 文字以内、description が 132 文字以内
- manifest.json が参照するファイル（icons、action のアイコンとポップアップ、content_scripts の js / css など）と、
  HTML（popup.html）が参照するファイル（<script src>、<link href>、<img src>）がすべて ZIP に入っている。
  HTML が外部のスクリプトを読み込んでいない
- アイコンが PNG で、縦横の大きさが manifest のキー（16 / 48 / 128）と一致する
"""

import argparse
import hashlib
import json
import os
import posixpath
import re
import struct
import sys
import tempfile
import unicodedata
import zipfile
from html.parser import HTMLParser
from pathlib import Path

# リポジトリのルート（このファイルは store-assets/tools/ にある）
ROOT = Path(__file__).resolve().parents[2]

# ZIP に入れるファイル（リポジトリのルートからの相対パス。区切りは "/"）
ALLOWLIST = (
    "manifest.json",
    "shared.js",
    "content.js",
    "colorize.js",
    "autobuttons.js",
    "cardurl.js",
    "content.css",
    "popup.html",
    "popup.css",
    "popup.js",
    "icons/icon16.png",
    "icons/icon48.png",
    "icons/icon128.png",
)

# 入っていたら必ず失敗にするもの（ALLOWLIST の誤編集への保険）
FORBIDDEN_PREFIXES = (".claude/", ".git/", "store-assets/", "dist/", "__MACOSX/")
FORBIDDEN_NAMES = ("README.md", ".gitattributes", ".gitignore", ".DS_Store")

FIXED_DATE_TIME = (2000, 1, 1, 0, 0, 0)  # ZIP 内の全エントリーの日時
FILE_MODE = 0o100644  # 通常ファイル rw-r--r--
NAME_MAX = 75
DESCRIPTION_MAX = 132
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
VERSION_RE = re.compile(r"^(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4})){0,3}$")
EXTERNAL_RE = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")


class Checks:
    """検証結果を集める。"""

    def __init__(self):
        self.results = []  # (ok, message)

    def ok(self, message):
        self.results.append((True, message))

    def fail(self, message):
        self.results.append((False, message))

    def check(self, condition, ok_message, fail_message):
        if condition:
            self.ok(ok_message)
        else:
            self.fail(fail_message)
        return condition

    @property
    def failed(self):
        return [m for ok, m in self.results if not ok]


def setup_console():
    # Windows のコンソール（cp932 など）で表示できない文字があっても落ちないようにする
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def parse_json_strict(data, label, checks):
    """BOM とキーの重複も失敗として扱う JSON の読み込み。失敗したら None。"""
    if data.startswith(b"\xef\xbb\xbf"):
        checks.fail("%s の先頭に BOM があります（BOM なしの UTF-8 で保存してください）" % label)
        return None
    duplicates = []

    def hook(pairs):
        seen = set()
        for key, _ in pairs:
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        return dict(pairs)

    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=hook)
    except (UnicodeDecodeError, ValueError) as e:
        checks.fail("%s が JSON として正しくありません: %s" % (label, e))
        return None
    if duplicates:
        checks.fail("%s に重複したキーがあります: %s" % (label, ", ".join(sorted(set(duplicates)))))
        return None
    if not isinstance(obj, dict):
        checks.fail("%s の最上位がオブジェクトではありません" % label)
        return None
    checks.ok("%s は JSON として正しい" % label)
    return obj


def normalize_ref(ref, base_dir=""):
    """参照パスを ZIP 内のパスにする。外部 URL・空・アンカーだけのものは None。ルートの外を指すなら ValueError。"""
    ref = ref.strip()
    if not ref or ref.startswith("#") or EXTERNAL_RE.match(ref):
        return None
    ref = ref.split("#", 1)[0].split("?", 1)[0]
    if ref.startswith("/"):
        path = posixpath.normpath(ref.lstrip("/"))
    else:
        path = posixpath.normpath(posixpath.join(base_dir, ref))
    if path == "." or path.startswith("../") or path == "..":
        raise ValueError(ref)
    return path


def manifest_refs(manifest):
    """manifest.json が参照するファイルを (説明, パス) の一覧で返す。"""
    refs = []

    def add(label, value):
        if isinstance(value, str):
            refs.append((label, value))
        elif isinstance(value, dict):
            for k, v in value.items():
                add("%s.%s" % (label, k), v)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                add("%s[%d]" % (label, i), v)

    add("icons", manifest.get("icons"))
    action = manifest.get("action") or {}
    add("action.default_icon", action.get("default_icon"))
    add("action.default_popup", action.get("default_popup"))
    for i, cs in enumerate(manifest.get("content_scripts") or []):
        add("content_scripts[%d].js" % i, cs.get("js"))
        add("content_scripts[%d].css" % i, cs.get("css"))
    background = manifest.get("background") or {}
    add("background.service_worker", background.get("service_worker"))
    add("options_page", manifest.get("options_page"))
    add("options_ui.page", (manifest.get("options_ui") or {}).get("page"))
    add("side_panel.default_path", (manifest.get("side_panel") or {}).get("default_path"))
    add("devtools_page", manifest.get("devtools_page"))
    add("chrome_url_overrides", manifest.get("chrome_url_overrides"))
    for i, war in enumerate(manifest.get("web_accessible_resources") or []):
        for r in war.get("resources") or []:
            if "*" not in r:  # ワイルドカードは確かめない
                add("web_accessible_resources[%d]" % i, r)
    return refs


class RefParser(HTMLParser):
    """HTML の <script src>、<link href>、<img src> を集める。"""

    def __init__(self):
        HTMLParser.__init__(self)
        self.refs = []  # (タグ, 属性名, 値)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and a.get("src"):
            self.refs.append(("script", "src", a["src"]))
        elif tag == "link" and a.get("href"):
            self.refs.append(("link", "href", a["href"]))
        elif tag == "img" and a.get("src"):
            self.refs.append(("img", "src", a["src"]))


def png_size(data):
    """PNG の (幅, 高さ)。PNG でなければ None。"""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def is_forbidden(name):
    base = name.rsplit("/", 1)[-1]
    return name.startswith(FORBIDDEN_PREFIXES) or base in FORBIDDEN_NAMES or name in FORBIDDEN_NAMES


def resolve_out(out_arg, version):
    filename = "tre-hiro-%s.zip" % version
    if out_arg is None:
        return ROOT / "dist" / filename
    out = Path(out_arg)
    if not out.is_absolute():
        out = Path.cwd() / out
    if out.suffix.lower() == ".zip":
        return out
    return out / filename


def build_zip(out_path, files):
    """files: [(arcname, bytes)]。一時ファイルに書いてから置き換える。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tre-hiro-", suffix=".zip", dir=str(out_path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            for arcname, data in files:
                info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3  # どの OS で作っても同じ属性にする
                info.external_attr = FILE_MODE << 16
                zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.chmod(tmp, 0o644)  # mkstemp は 0600 で作るので、通常のファイルと同じにする
        os.replace(tmp, str(out_path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def verify_zip(out_path, expected_version, sources):
    """出来上がった ZIP を開き直して検証する。sources: {arcname: リポジトリのファイルの bytes}"""
    checks = Checks()
    try:
        zf = zipfile.ZipFile(str(out_path))
    except zipfile.BadZipFile as e:
        checks.fail("ZIP を開けません: %s" % e)
        return checks, []
    with zf:
        infos = zf.infolist()
        names = [i.filename for i in infos]
        bad = zf.testzip()
        checks.check(bad is None, "ZIP が壊れていない（CRC が一致）", "ZIP のエントリーが壊れています: %s" % bad)

        # 中身が ALLOWLIST と完全に一致するか
        dupes = sorted(set(n for n in names if names.count(n) > 1))
        checks.check(not dupes, "同じ名前のエントリーがない", "同じ名前のエントリーがあります: %s" % ", ".join(dupes))
        extra = sorted(set(names) - set(ALLOWLIST))
        missing = sorted(set(ALLOWLIST) - set(names))
        checks.check(not extra, "余分なファイルがない（ALLOWLIST の %d ファイルだけ）" % len(ALLOWLIST),
                     "ALLOWLIST にないファイルが入っています: %s" % ", ".join(extra))
        checks.check(not missing, "ALLOWLIST のファイルがすべて入っている",
                     "入っていないファイルがあります: %s" % ", ".join(missing))
        forbidden = [n for n in names if is_forbidden(n)]
        checks.check(not forbidden, "入れてはいけないもの（.claude/、.git/、README.md、store-assets/ など）がない",
                     "入れてはいけないファイルが入っています: %s" % ", ".join(forbidden))
        odd = [n for n in names if "\\" in n or n.startswith("/") or n.endswith("/") or ".." in n.split("/")]
        checks.check(not odd, "パスの形式が正しい（区切りは /、絶対パス・ディレクトリのエントリーなし）",
                     "パスの形式が正しくないエントリーがあります: %s" % ", ".join(odd))

        contents = {}
        for n in names:
            contents[n] = zf.read(n)
        differ = [n for n in names if n in sources and contents[n] != sources[n]]
        checks.check(not differ, "各ファイルの中身がリポジトリのファイルと同じ",
                     "リポジトリのファイルと中身が違います: %s" % ", ".join(differ))

    # manifest.json
    if not checks.check("manifest.json" in contents, "manifest.json が ZIP のルートにある",
                        "ZIP のルートに manifest.json がありません"):
        return checks, infos
    manifest = parse_json_strict(contents["manifest.json"], "ZIP 内の manifest.json", checks)
    if manifest is None:
        return checks, infos

    checks.check(manifest.get("manifest_version") == 3, "manifest_version が 3",
                 "manifest_version が 3 ではありません: %r" % manifest.get("manifest_version"))
    version = manifest.get("version")
    if checks.check(isinstance(version, str) and VERSION_RE.match(version) is not None
                    and all(int(p) <= 65535 for p in version.split(".")),
                    "version の形式が正しい（%s）" % version, "version の形式が正しくありません: %r" % version):
        checks.check(version == expected_version, "version %s がファイル名と一致" % version,
                     "version が一致しません（ZIP 内 %s、ファイル名 %s）" % (version, expected_version))
    name = manifest.get("name")
    checks.check(isinstance(name, str) and 0 < len(name) <= NAME_MAX,
                 "name が %d 文字以内（%s、%d 文字）" % (NAME_MAX, name, len(name or "")),
                 "name が空か %d 文字を超えています: %r" % (NAME_MAX, name))
    desc = manifest.get("description")
    checks.check(isinstance(desc, str) and 0 < len(desc) <= DESCRIPTION_MAX,
                 "description が %d 文字以内（%d 文字）" % (DESCRIPTION_MAX, len(desc or "")),
                 "description が空か %d 文字を超えています（%d 文字）" % (DESCRIPTION_MAX, len(desc or "")))

    # manifest.json が参照するファイル
    refs = manifest_refs(manifest)
    html_pages = []
    missing_refs = []
    for label, ref in refs:
        try:
            path = normalize_ref(ref)
        except ValueError:
            missing_refs.append("%s=%s（ルートの外）" % (label, ref))
            continue
        if path is None:
            missing_refs.append("%s=%s（パッケージ外の URL）" % (label, ref))
        elif path not in contents:
            missing_refs.append("%s=%s" % (label, ref))
        elif path.lower().endswith((".html", ".htm")) and path not in html_pages:
            html_pages.append(path)
    checks.check(refs and not missing_refs,
                 "manifest.json が参照する %d 件のファイルがすべて入っている" % len(refs),
                 "manifest.json が参照するファイルが入っていません（新しいファイルなら ALLOWLIST に追加してください）: %s"
                 % ", ".join(missing_refs or ["（参照が0件）"]))

    # HTML（popup.html など）が参照するファイル
    for page in html_pages:
        parser = RefParser()
        try:
            parser.feed(contents[page].decode("utf-8"))
            parser.close()
        except UnicodeDecodeError as e:
            checks.fail("%s を UTF-8 として読めません: %s" % (page, e))
            continue
        base = posixpath.dirname(page)
        bad_refs = []
        remote_scripts = []
        count = 0
        for tag, attr, value in parser.refs:
            try:
                path = normalize_ref(value, base)
            except ValueError:
                bad_refs.append("<%s %s=%s>（ルートの外）" % (tag, attr, value))
                continue
            if path is None:
                if tag == "script" and EXTERNAL_RE.match(value.strip()):
                    remote_scripts.append(value)
                continue
            count += 1
            if path not in contents:
                bad_refs.append("<%s %s=%s>" % (tag, attr, value))
        checks.check(not remote_scripts, "%s が外部のスクリプトを読み込んでいない" % page,
                     "%s が外部のスクリプトを読み込んでいます: %s" % (page, ", ".join(remote_scripts)))
        checks.check(not bad_refs, "%s が参照する %d 件のファイルがすべて入っている" % (page, count),
                     "%s が参照するファイルが入っていません（新しいファイルなら ALLOWLIST に追加してください）: %s"
                     % (page, ", ".join(bad_refs)))

    # アイコンの大きさ
    icon_specs = []
    for label, value in (("icons", manifest.get("icons")),
                         ("action.default_icon", (manifest.get("action") or {}).get("default_icon"))):
        if isinstance(value, dict):
            for k, v in value.items():
                icon_specs.append((label, k, v))
    icon_problems = []
    for label, key, ref in icon_specs:
        try:
            path = normalize_ref(ref)
        except ValueError:
            continue
        if path not in contents:
            continue  # 上の参照の検証で失敗にしている
        size = png_size(contents[path])
        if size is None:
            icon_problems.append("%s.%s=%s（PNG ではない）" % (label, key, ref))
        elif not key.isdigit() or size != (int(key), int(key)):
            icon_problems.append("%s.%s=%s（%dx%d）" % (label, key, ref, size[0], size[1]))
    checks.check(icon_specs and not icon_problems,
                 "アイコンが PNG で、大きさが manifest のキーと一致（%d 件）" % len(icon_specs),
                 "アイコンの形式か大きさが合いません: %s" % ", ".join(icon_problems or ["（アイコンの指定が0件）"]))

    # ALLOWLIST のうち、どこからも参照されていないファイル（警告だけ）
    referenced = {"manifest.json"}
    for _, ref in refs:
        try:
            p = normalize_ref(ref)
        except ValueError:
            p = None
        if p:
            referenced.add(p)
    for page in html_pages:
        parser = RefParser()
        try:
            parser.feed(contents[page].decode("utf-8"))
        except UnicodeDecodeError:
            continue
        for _, _, value in parser.refs:
            try:
                p = normalize_ref(value, posixpath.dirname(page))
            except ValueError:
                p = None
            if p:
                referenced.add(p)
    unreferenced = [n for n in ALLOWLIST if n not in referenced]
    if unreferenced:
        print("注意: どこからも参照されていないファイルがあります（不要なら ALLOWLIST から外してください）: %s"
              % ", ".join(unreferenced))
    return checks, infos


def main(argv=None):
    setup_console()
    parser = argparse.ArgumentParser(
        description="トレひろの Chrome ウェブストア提出用 ZIP を作り、中身を検証します。")
    parser.add_argument("--out", metavar="PATH",
                        help="出力先。フォルダを指定するとその中に tre-hiro-<version>.zip を作る。"
                             ".zip で終わるパスならそのファイル名で作る（既定: <リポジトリ>/dist/）")
    args = parser.parse_args(argv)

    pre = Checks()

    # 1. リポジトリのファイルを読む（足りなければ ZIP を作らない）
    sources = {}
    for name in ALLOWLIST:
        path = ROOT / name
        if path.is_file():
            sources[name] = path.read_bytes()
        else:
            pre.fail("ファイルがありません: %s" % name)
    if "manifest.json" not in sources:
        return report(pre, None, None, [])
    manifest = parse_json_strict(sources["manifest.json"], "manifest.json", pre)
    if manifest is None or pre.failed:
        return report(pre, None, None, [])
    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        pre.fail("manifest.json の version の形式が正しくありません: %r" % version)
        return report(pre, None, None, [])

    # 2. ZIP を作る（manifest.json を先頭に、残りはパスの昇順）
    out_path = resolve_out(args.out, version)
    order = ["manifest.json"] + sorted(n for n in ALLOWLIST if n != "manifest.json")
    build_zip(out_path, [(n, sources[n]) for n in order])

    # 3. 開き直して検証する
    checks, infos = verify_zip(out_path, version, sources)
    checks.results[:0] = pre.results
    return report(checks, out_path, manifest, infos)


def rjust_display(text, width):
    """全角文字を2桁と数えて右寄せする（表の見出し用）。"""
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
    return " " * max(0, width - w) + text


def report(checks, out_path, manifest, infos):
    if out_path is not None and infos:
        try:
            shown = out_path.relative_to(ROOT)
        except ValueError:
            shown = out_path
        print("トレひろ v%s の提出用 ZIP: %s" % (manifest.get("version"), shown))
        print("")
        print("  %s  %s  %s" % (rjust_display("サイズ(B)", 10), rjust_display("圧縮後(B)", 10), "ファイル"))
        total = 0
        for info in infos:
            total += info.file_size
            print("  %10s  %10s  %s" % ("{:,}".format(info.file_size), "{:,}".format(info.compress_size),
                                        info.filename))
        zip_bytes = out_path.read_bytes() if out_path.exists() else b""
        print("  " + "-" * 40)
        print("  %d ファイル、展開後 %s バイト、ZIP %s バイト" % (len(infos), "{:,}".format(total),
                                                       "{:,}".format(len(zip_bytes))))
        print("  SHA-256: %s" % hashlib.sha256(zip_bytes).hexdigest())
        print("")

    print("検証:")
    for ok, message in checks.results:
        print("  %s  %s" % ("OK" if ok else "NG", message))
    print("")
    if checks.failed:
        if out_path is not None and out_path.exists():
            out_path.unlink()
            print("検証に失敗したため、ZIP を削除しました。")
        print("結果: 失敗（%d 件）" % len(checks.failed))
        return 1
    print("結果: すべての検証に合格しました。この ZIP をそのまま Chrome ウェブストアにアップロードできます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
