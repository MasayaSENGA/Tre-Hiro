"""再現ページ（模型）を手元のブラウザで確かめるための小さな HTTP サーバー。

    python3 store-assets/tools/mock/serve.py            # http://127.0.0.1:8730/ で待ち受ける
    python3 store-assets/tools/mock/serve.py --port 9000

開く URL（撮影時と同じ道順。撮影では同じものを https://trello.com/... として返している）:
    http://127.0.0.1:8730/b/Mk7Wb2Qa/web-renewal                    ボード
    http://127.0.0.1:8730/c/Hr8dT0pK/14-top-page-design             カード詳細（コメント欄を開いた状態）
    http://127.0.0.1:8730/c/Hr8dT0pK/14-top-page-design?comments=closed   コメント欄を閉じた状態

ここで見えるのは拡張を当てていない「Trello 標準」の見た目。トレひろのコンテンツスクリプトは
https://trello.com/* にしか入らないので、拡張を当てた見た目は capture_raw.py で確かめる。
標準ライブラリだけで動き、127.0.0.1 だけで待ち受ける（外からはつながらない）。
"""

from __future__ import annotations

import argparse
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True   # tools/ に __pycache__ を作らない
sys.path.insert(0, os.path.dirname(HERE))
import cdp  # noqa: E402

SITE = cdp.MockSite(HERE)
START = "/b/Mk7Wb2Qa/web-renewal"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("", "/"):
            self.send_response(302)
            self.send_header("Location", START)
            self.end_headers()
            return
        status, ctype, body, _ = SITE.resolve_path(path)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8730)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"http://127.0.0.1:{args.port}{START} で開けます（Ctrl+C で終了）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
