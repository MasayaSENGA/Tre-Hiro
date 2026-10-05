#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""トレひろ の Chrome ウェブストア用画像を合成して検査する。

使い方（リポジトリのルートで実行）:

    python3 store-assets/tools/compose/render_assets.py
        スクリーンショット 5 枚とプロモーションタイル 2 枚を store-assets/ の下に書き出して検査する（上書き）。
    python3 store-assets/tools/compose/render_assets.py --out-root DIR
        同じフォルダ構成（screenshots/、promo/）で DIR の下に書き出す（store-assets/ の画像は変えない。
        途中のファイルは --out-root に関係なく、git の対象外の tools/compose/build/ に書く）。
    python3 store-assets/tools/compose/render_assets.py --preview-dir DIR
        確認用の縮小版も書く（スクリーンショットは 640x400 ＝ストアの表示サイズ、タイルは半分の大きさ）。
    python3 store-assets/tools/compose/render_assets.py --only 02-wide.html 04-color.html
        指定したページだけ描き出す。
    python3 store-assets/tools/compose/render_assets.py --browser PATH
        Chrome の実行ファイルを指定する（既定は自動検出。macOS は /Applications/Google Chrome.app/...、
        Windows は C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe。環境変数 CHROME_PATH でも可）。
    python3 store-assets/tools/compose/render_assets.py --font FONT
        文字のフォント。FONT はフォントファイル（.ttf / .otf / .ttc / .woff2。可変フォント可）か "hiragino"。
        既定は macOS ではヒラギノ角ゴシック（"hiragino"、OS のフォントを local() で参照）、Windows では
        C:\\Windows\\Fonts\\NotoSansJP-VF.ttf（なければユーザーのフォントフォルダ）。環境変数 TREHIRO_FONT でも可。
    python3 store-assets/tools/compose/render_assets.py --tmp-dir DIR
        一時ファイル（Chrome のプロファイル、2 倍の撮影画像）の置き場所（既定はシステムの一時フォルダ）。

必要なもの: Python 3.9 以上、Pillow、Google Chrome（拡張機能は使わない。file:// のページを開くだけ）。

書き出すもの（--out-root の下、既定は store-assets/）:
    screenshots/01-hero.png … 05-privacy.png                      1280x800  RGB（24bit）
    promo/small-tile-440x280.png, promo/marquee-1400x560.png      440x280 / 1400x560  RGB
途中のファイルは store-assets/tools/compose/build/（git の対象外）に置く。
ストアアイコン store-assets/icon/store-icon-128.png は render_icons.py の担当なので、ここでは検査だけする。

手順
  1. prepare(): raw/ の撮影画像（deviceScaleFactor 2）を build/*.png に切り出す。切り出すだけで、
     写っている画面の画素は一切描き直さない。切り出す範囲は raw/manifest.json に撮影担当が記録した
     要素の矩形（CSS px）から決める（画素の解析はしない。03 の下端だけは、文字の行を切らない位置を目視で決めた
     固定値で、矩形との前後関係を検査する）。切り出し範囲と、重ね描き（目印・矢印）に使う
     要素の矩形を build/geometry.js に書く。ブランドのアイコンは tools/icon/render_icons.py の描画関数で
     512px に描き（icons/icon128.png と同じ図柄。128px に縮めると平均差 1 未満）、絵柄の部分
     （384x384）を build/icon-art.png にする。フォントの指定は build/font.css に書く。
  2. render(): 各ページを最終の大きさ（CSS px）で組み、ヘッドレスの Chrome で deviceScaleFactor 2 で
     撮影し、LANCZOS で正確な大きさに縮め、24bit RGB にして保存する。
  3. 検査（どれかに通らなければ "FAILED" を表示して終了コード 1）:
     - 文言が EXPECTED と 1 文字ずつ一致する（空白・改行は無視）。各セレクタはページに 1 つだけ
     - 文字のはみ出し・切れ・意図しない折り返しがない（改行はすべて明示。common.js が検査）
     - 要素（data-block）どうしが重ならない。画像は元の画素より拡大しない（元画像の px ≥ 表示 CSS px × 2）
     - 「Trello」の文字は「トレひろ」より大きくしない（大見出しには入れない）。どの画像にもブランド名がある
     - 注記の文字と背景のコントラストが 7:1 以上（2 倍の撮影画像の画素で測る）
     - 出力の大きさとモードが正確（1280x800 / 440x280 / 1400x560、RGB）
     - store-assets/icon/store-icon-128.png が 128x128 RGBA で、各辺 16px が完全に透明
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
ASSETS = TOOLS.parent
REPO = ASSETS.parent
RAW = ASSETS / "raw"
BUILD = HERE / "build"
STORE_ICON = ASSETS / "icon" / "store-icon-128.png"
DPR = 2

sys.dont_write_bytecode = True     # tools/ や tools/icon/ に __pycache__ を作らない
sys.path.insert(0, str(TOOLS))
import cdp  # noqa: E402

PAGES = [
    # (html, 出力（--out-root からの相対）, (幅, 高さ))。すべて RGB で保存する
    ("01-hero.html", Path("screenshots") / "01-hero.png", (1280, 800)),
    ("02-wide.html", Path("screenshots") / "02-wide.png", (1280, 800)),
    ("03-ratio.html", Path("screenshots") / "03-ratio.png", (1280, 800)),
    ("04-color.html", Path("screenshots") / "04-color.png", (1280, 800)),
    ("05-privacy.html", Path("screenshots") / "05-privacy.png", (1280, 800)),
    ("small-tile.html", Path("promo") / "small-tile-440x280.png", (440, 280)),
    ("marquee.html", Path("promo") / "marquee-1400x560.png", (1400, 560)),
]

# 確定した文言（listing.md・各 HTML と 1 文字ずつ一致させる。空白と改行は比べない）
FOOTNOTE = "※非公式ツールです。Trello・Atlassian とは関係ありません。Trello は Atlassian の商標です。"
FOOTNOTE2 = "※画面は、Trello を再現した確認用ページにトレひろの実際のコードを当てて撮影したものです。内容は架空です。"
BRAND = "トレひろ"
EXPECTED = {
    "01-hero.html": {
        ".headline": "カード詳細を、画面いっぱいに",
        ".sub": "Trello のカード詳細を広げて、説明欄とコメント欄の比率も自由に",
        ".fig-cap": "トレひろで幅95%・比率60:40に設定した場合",
        ".dim-pill": "ウィンドウ幅の95%",
        ".brand-name": BRAND, ".footnote": FOOTNOTE, ".footnote2": FOOTNOTE2,
    },
    "02-wide.html": {
        ".headline": "横に長い説明や表も、広々と",
        ".sub": "標準の幅と、トレひろ（幅95%・比率60:40）の比較",
        ".lbl-before": "Trello 標準",
        ".lbl-after": "トレひろ（幅95%・比率60:40）",
        ".brand-name": BRAND, ".footnote": FOOTNOTE, ".footnote2": FOOTNOTE2,
    },
    "03-ratio.html": {
        ".headline": "説明欄とコメント欄の比率を自由に",
        ".sub": "スライダーを動かすと、開いているカードにその場で反映",
        ".lbl-r75": "75:25（説明欄を広く）",
        ".lbl-r35": "35:65（コメント欄を広く）",
        ".brand-name": BRAND, ".footnote": FOOTNOTE, ".footnote2": FOOTNOTE2,
    },
    "04-color.html": {
        ".headline": "カードをラベルの色で塗り分け",
        ".sub": "左端の帯はラベルごとに色分け。色の濃さも調整できます",
        ".lbl-before": "色付けなし（Trello 標準の見た目）",
        ".lbl-after": "トレひろで色付け（濃さ16%）",
        ".brand-name": BRAND, ".footnote": FOOTNOTE, ".footnote2": FOOTNOTE2,
    },
    "05-privacy.html": {
        ".headline": "権限は最小限、外部送信なし",
        ".sub": "動くのは trello.com のページだけ。読み取った情報は保存も送信もしません",
        # fact-1: trello.com で動くコンテンツスクリプトもサイトへのアクセス権（インストール時の確認）になるため、
        #         storage だけとは書かない（facts.md 12章 R4）。fact-4: 読むのはラベル色だけではない（10章・R3）
        ".fact-1 .t": "権限は、設定の保存（storage）と trello.com へのアクセスだけ",
        ".fact-2 .t": "動くのは trello.com のページだけ",
        ".fact-3 .t": "外部送信・アクセス解析なし",
        ".fact-4 .t": "カードの文字は読まない。保存も送信もしない",
        ".brand-name": BRAND, ".footnote": FOOTNOTE,
    },
    "small-tile.html": {".name": BRAND, ".tag": "カード詳細を、画面いっぱいに"},
    "marquee.html": {
        ".name": BRAND,
        ".tagline": "Trello のカード詳細を、画面いっぱいに",
        ".support": "説明欄とコメント欄の比率調整・ラベル色の塗り分け（非公式ツール）",
    },
}
# 2 行目の注記（再現画面の説明）は、再現画面が写っていない 05 とタイルには出さない
FORBIDDEN = {
    "05-privacy.html": [".footnote2"],
    "small-tile.html": [".footnote", ".footnote2"],
    "marquee.html": [".footnote2"],
}
MIN_FOOTNOTE_CONTRAST = 7.0


def show(path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# 1. 切り出し（raw/manifest.json の矩形だけを使う）
# ---------------------------------------------------------------------------
def _r(v):
    """manifest の矩形 → (x0, y0, x1, y1)（CSS px）。{"rect", "visible"} の形なら見えている範囲を使う。"""
    if v is None:
        return None
    if "rect" in v:
        v = v.get("visible") or v["rect"]
    return (v["x"], v["y"], v["x"] + v["width"], v["y"] + v["height"])


def load_manifest() -> dict:
    m = json.loads((RAW / "manifest.json").read_text(encoding="utf-8"))
    shots = {s["file"]: s for s in m["shots"]}
    if m.get("dpr") != DPR:
        raise SystemExit(f"raw/manifest.json: dpr {m.get('dpr')} != {DPR}")
    return shots


def prepare(font_css: str) -> dict:
    BUILD.mkdir(parents=True, exist_ok=True)
    shots = load_manifest()
    geom: dict = {}

    def crop(name, src, box_css, boxes_css=None, **extra):
        """box_css = (x0, y0, x1, y1) CSS px をそのまま 2 倍の画素で切り出す。boxes は切り出し後の CSS px。"""
        shot = shots[src]
        im = Image.open(RAW / src)
        im.load()
        if list(im.size) != list(shot["size"]):
            raise SystemExit(f"{src}: size {im.size} != manifest {shot['size']}")
        x0, y0, x1, y1 = box_css
        px = [round(x0 * DPR), round(y0 * DPR), round(x1 * DPR), round(y1 * DPR)]
        px = [max(0, px[0]), max(0, px[1]), min(im.width, px[2]), min(im.height, px[3])]
        out = im.crop(px)
        out.save(BUILD / f"{name}.png", optimize=False, compress_level=1)
        ox, oy = px[0] / DPR, px[1] / DPR
        rel = {}
        for k, b in (boxes_css or {}).items():
            if b is None:
                continue
            rel[k] = [round(b[0] - ox, 2), round(b[1] - oy, 2), round(b[2] - ox, 2), round(b[3] - oy, 2)]
        geom[name] = {"src": src, "crop_px": px, "w": out.width, "h": out.height,
                      "css_w": out.width / DPR, "css_h": out.height / DPR, "boxes": rel, **extra}

    def rects(src):
        return shots[src]["rects"]

    # --- 01: カード詳細（幅 95%・比率 60:40）。ダイアログの左右に暗幕を残し、表の下の箇条書き 1 行目まで -----
    r = rects("card_default.png")
    d, main, aside, table = _r(r["dialog"]), _r(r["main"]), _r(r["aside_visible"]), _r(r["table"])
    vw = r["viewport"]["width"]
    # 下端は「最後のコメントの下端 - 2px」。右のコメント欄は項目の切れ目、左の説明欄は箇条書き 1 行目と 2 行目の
    # 間になり、文字の行を途中で切らない（表の最終行も全部入る）。raw/card_default.png で目視確認済み
    last_comment = _r(r["comment_items"][-1])
    hero_y1 = last_comment[3] - 2
    if not table[3] + 20 <= hero_y1 <= d[3]:
        raise SystemExit(f"hero_card: bottom {hero_y1} is not between the table end and the dialog end")
    crop("hero_card", "card_default.png", (0, d[1] - 14, vw, hero_y1),
         {"dialog": d, "main": main, "aside": aside, "table": table},
         measured=shots["card_default.png"]["measured"], viewport=r["viewport"])

    # --- 02: 説明欄（見出し・本文・横に長い表）。OFF（Trello 標準）と ON（95%・60:40）の同じ範囲 ----------
    for name, src in (("wide_off", "card_off.png"), ("wide_on", "card_default.png")):
        r = rects(src)
        desc, body, table, dlg = _r(r["description"]), _r(r["description_body"]), _r(r["table"]), _r(r["dialog"])
        y1 = min(table[3] + 10, dlg[3] - 1)
        crop(name, src, (desc[0] - 10, desc[1] - 8, desc[2] + 10, y1),
             {"description": desc, "body": body, "table": table},
             measured=shots[src]["measured"], rows=shots[src]["table_row_heights"],
             dialog_w=shots[src]["measured"]["dialog"], viewport=shots[src]["viewport"])

    # --- 03: 比率 75:25 / 35:65。ダイアログ全幅、本体の上部（左はタイトル〜、右はコメント） --------------------
    # 下端は、左右どちらでも文字の行や入力欄を途中で切らない位置（raw を目視して決めた CSS px）。
    #   75:25 … 説明の本文 2 行目の下（表の上端 429 の手前）。右はコメント 2 の枠の上端だけが入る
    #   35:65 … 「メンバー / ラベル」の行の下（「期限」の見出しより上）。右はコメント 2 の下端とコメント 3 の間
    RATIO_Y1 = {"card_r75.png": 421, "card_r35.png": 372}
    for name, src in (("ratio_r75", "card_r75.png"), ("ratio_r35", "card_r35.png")):
        r = rects(src)
        d, main, aside = _r(r["dialog"]), _r(r["main"]), _r(r["aside_visible"])
        y1 = RATIO_Y1[src]
        meta, table = _r(r["meta"]), _r(r["table"])
        if not (meta[1] + 40 <= y1 < table[1]):
            raise SystemExit(f"{name}: bottom {y1} is outside the expected range ({meta[1] + 40}..{table[1]})")
        crop(name, src, (d[0], main[1], d[2], y1),
             {"dialog": d, "main": main, "aside": aside},
             measured=shots[src]["measured"])

    # --- ポップアップ（本物の popup.html）: 全体と、比率・色付けの欄 -----------------------------------
    p = rects("popup_default.png")
    body = _r(p["body"])
    crop("popup_default", "popup_default.png", body,
         {k: _r(v) for k, v in p.items()}, texts=shots["popup_default.png"]["popup_ui"]["texts"])
    for name, src in (("pop_ratio_r75", "popup_r75.png"), ("pop_ratio_r35", "popup_r35.png")):
        p = rects(src)
        f = _r(p["descRatio_field"])
        crop(name, src, (0, f[1], 300, f[3]), {"field": f},
             texts=shots[src]["popup_ui"]["texts"])
    p = rects("popup_default.png")
    f = _r(p["colorField"])
    crop("pop_color", "popup_default.png", (0, f[1], 300, f[3]), {"field": f, "swatch": _r(p["swatch"])},
         texts=shots["popup_default.png"]["popup_ui"]["texts"])

    # --- 04: ボードのリスト 2 本（未着手・作業中）。色付けなし / 色付け 16% の同じ範囲 ---------------------
    for name, src in (("board_off", "board_off.png"), ("board_color", "board_color.png")):
        r = rects(src)
        lists = [_r(x["rect"]) for x in r["lists"][:2]]
        x0, x1 = lists[0][0] - 8, lists[1][2] + 8
        y0, y1 = lists[0][1] - 8, max(b[3] for b in lists) + 8
        cards = {f"card{i}": _r(c) for i, c in enumerate(r["cards"]) if _r(c)[0] < x1}
        crop(name, src, (x0, y0, x1, y1), cards,
             settings=shots[src]["settings_stored"],
             card_names=[c["name"] for c in r["cards"] if _r(c)[0] < x1])

    # --- ブランドのアイコン（icons/icon128.png と同じ描画関数で 512px に描き、絵柄 384x384 を使う） -------
    icon_src = "render_icons.draw_full(512)"
    try:
        sys.path.insert(0, str(TOOLS / "icon"))
        import render_icons  # noqa: E402
        big = render_icons.draw_full(512, 4, 64, render_icons.GEOM)
    except Exception as e:  # 描画関数が使えないときは icon128.png（絵柄 96px）で代える
        print(f"  note: render_icons.draw_full unavailable ({e}); using icons/icon128.png")
        big = Image.open(REPO / "icons" / "icon128.png").convert("RGBA")
        icon_src = "icons/icon128.png"
    art = big.crop(big.getchannel("A").getbbox())
    art.save(BUILD / "icon-art.png", optimize=False, compress_level=1)
    geom["icon_art"] = {"src": icon_src, "w": art.width, "h": art.height}

    (BUILD / "font.css").write_text(font_css, encoding="utf-8")
    (BUILD / "geometry.js").write_text(
        "// render_assets.py が書き出す。boxes は切り出し後の CSS px [x0, y0, x1, y1]（画像の w/h は画素）\n"
        "window.GEOM = " + json.dumps(geom, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
    return geom


# ---------------------------------------------------------------------------
# フォント
# ---------------------------------------------------------------------------
HIRAGINO = {400: "HiraginoSans-W3", 500: "HiraginoSans-W5", 600: "HiraginoSans-W6",
            700: "HiraginoSans-W7", 800: "HiraginoSans-W8", 900: "HiraginoSans-W9"}


def default_font() -> str:
    env = os.environ.get("TREHIRO_FONT")
    if env:
        return env
    if sys.platform == "darwin":
        return "hiragino"
    if sys.platform == "win32":
        cands = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "NotoSansJP-VF.ttf"]
        if os.environ.get("LOCALAPPDATA"):
            cands.append(Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts" / "NotoSansJP-VF.ttf")
        for c in cands:
            if c.is_file():
                return str(c)
        raise SystemExit("Noto Sans JP (NotoSansJP-VF.ttf) not found; pass --font <font file>")
    for c in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"):
        if Path(c).is_file():
            return c
    raise SystemExit("no Japanese font found; pass --font <font file>")


def make_font_css(font: str) -> tuple[str, str]:
    head = "/* render_assets.py が書き出す（--font / TREHIRO_FONT）。common.css が読み込む */\n"
    if font.lower() == "hiragino":
        rules = "".join(
            '@font-face { font-family: "TH Sans"; src: local("%s"); font-weight: %d; font-display: block; }\n'
            % (ps, w) for w, ps in HIRAGINO.items())
        return head + rules, "Hiragino Sans (local: " + ", ".join(HIRAGINO.values()) + ")"
    p = Path(font)
    if not p.is_file():
        raise SystemExit(f"font not found: {font} (use --font <file> or --font hiragino)")
    fmt = {".ttf": "truetype", ".otf": "opentype", ".ttc": "collection", ".woff2": "woff2", ".woff": "woff"}.get(
        p.suffix.lower(), "truetype")
    rule = ('@font-face { font-family: "TH Sans"; src: url("%s") format("%s"); font-weight: 100 900; '
            'font-display: block; }\n' % (p.resolve().as_uri(), fmt))
    return head + rule, str(p)


# ---------------------------------------------------------------------------
# 2. 撮影と検査
# ---------------------------------------------------------------------------
def rel_lum(rgb) -> float:
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb[:3]
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b) -> float:
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def footnote_contrast(big: Image.Image, notes: list) -> list:
    """注記の行ボックスの上下の余白（字の無い帯）の画素を背景として、文字色とのコントラストの最小値を返す。"""
    out = []
    px = big.load()
    for n in notes:
        x0, y0, x1, y1 = [v * DPR for v in n["rect"]]
        x0, x1 = int(x0) + 2, int(x1) - 2
        rows = [int(y0) + 1, int(y0) + 2, int(y1) - 3, int(y1) - 2]
        worst = 99.0
        for y in rows:
            for x in range(x0, x1, 3):
                worst = min(worst, contrast(px[x, y], n["color"]))
        out.append((n["sel"], round(worst, 2)))
    return out


def render(pages, out_root: Path, browser_path, preview_dir=None, tmp_dir=None) -> list:
    problems = []
    tmp_root = Path(tmp_dir or tempfile.gettempdir())
    tmp_root.mkdir(parents=True, exist_ok=True)
    profile = tmp_root / "trehiro-compose-profile"
    cdp.kill_leftovers(str(profile))
    shutil.rmtree(profile, ignore_errors=True)
    browser = cdp.Browser(browser_path, str(profile), extra_args=[
        "--allow-file-access-from-files", "--hide-scrollbars", "--force-color-profile=srgb",
        "--disable-lcd-text", "--font-render-hinting=none", "--disable-gpu",
        "--disable-default-apps", "--disable-extensions", "--disable-sync",
    ])
    try:
        for html, rel_out, (w, h) in pages:
            out = out_root / rel_out
            issues = []
            s = browser.new_page(width=w, height=h, dpr=DPR)
            tmp = tmp_root / f"trehiro-{Path(html).stem}@2x.png"
            try:
                s.navigate((HERE / html).as_uri())
                s.wait_for("window.__READY === true", timeout=60)
                issues += s.evaluate("window.__ISSUES") or []
                notes = s.evaluate("window.__NOTES") or []
                for sel, want in EXPECTED.get(html, {}).items():
                    got = s.evaluate(
                        f"[...document.querySelectorAll({json.dumps(sel)})].map(e => e.textContent)")
                    if len(got or []) != 1:
                        issues.append(f"{sel}: expected exactly 1 element, found {len(got or [])}")
                        continue
                    got = "".join(got[0].split())
                    if got != "".join(want.split()):
                        issues.append(f"copy mismatch in {sel}: {got!r} != {want!r}")
                for sel in FORBIDDEN.get(html, []):
                    if s.evaluate(f"document.querySelectorAll({json.dumps(sel)}).length"):
                        issues.append(f"{sel} must not appear on this page")
                size = s.evaluate("(() => { const c = document.querySelector('.canvas');"
                                  " return [c.offsetWidth, c.offsetHeight]; })()")
                if list(size) != [w, h]:
                    issues.append(f"canvas is {size}, expected {[w, h]}")
                foot = s.evaluate("window.__FOOTNOTES") or []
                s.screenshot(str(tmp))
            finally:
                browser.close_page(s)
            big = Image.open(tmp).convert("RGB")
            if big.size != (w * DPR, h * DPR):
                issues.append(f"capture is {big.size}, expected {(w * DPR, h * DPR)}")
            for sel, c in footnote_contrast(big, foot):
                notes.append(f"note: contrast {sel} {c}:1")
                if c < MIN_FOOTNOTE_CONTRAST:
                    issues.append(f"footnote contrast {sel} {c}:1 < {MIN_FOOTNOTE_CONTRAST}:1")
            final = big.resize((w, h), Image.LANCZOS).convert("RGB")
            out.parent.mkdir(parents=True, exist_ok=True)
            final.save(out, optimize=True)
            try:
                tmp.unlink()
            except OSError:
                pass
            print(f"[{'OK' if not issues else 'ISSUES'}] {show(out)}  {final.size} {final.mode}")
            for n in notes:
                print("       ", n[len("note: "):] if n.startswith("note: ") else n)
            for i in issues:
                print("   !!", i)
                problems.append(f"{html}: {i}")
            if preview_dir:
                preview_dir.mkdir(parents=True, exist_ok=True)
                pw, ph = (640, 400) if (w, h) == (1280, 800) else (w // 2, h // 2)
                final.resize((pw, ph), Image.LANCZOS).save(preview_dir / f"preview-{out.stem}-{pw}x{ph}.png")
    finally:
        browser.close()
        cdp.kill_leftovers(str(profile))
        for _ in range(40):
            shutil.rmtree(profile, ignore_errors=True)
            if not profile.exists():
                break
            time.sleep(0.25)
    return problems


def verify(out_root: Path, pages) -> list:
    bad = []
    for _, rel_out, size in pages:
        path = out_root / rel_out
        im = Image.open(path)
        ok = im.size == size and im.mode == "RGB"
        print(f"  verify {'ok ' if ok else 'BAD'} {show(path)} {im.size} {im.mode}")
        if not ok:
            bad.append(f"{show(path)}: {im.size} {im.mode}, expected {size} RGB")
    # ストアアイコン（render_icons.py の担当。ここでは作り直さず検査だけ）
    im = Image.open(STORE_ICON)
    ok = im.size == (128, 128) and im.mode == "RGBA"
    if ok:
        a = im.getchannel("A")
        bands = [a.crop(b) for b in ((0, 0, 128, 16), (0, 112, 128, 128), (0, 0, 16, 128), (112, 0, 128, 128))]
        ok = all(b.getextrema()[1] == 0 for b in bands) and a.getbbox() is not None
    print(f"  verify {'ok ' if ok else 'BAD'} {show(STORE_ICON)} {im.size} {im.mode} "
          f"(opaque bbox {im.getchannel('A').getbbox() if im.mode == 'RGBA' else '-'}, 16px transparent margin)")
    if not ok:
        bad.append(f"{show(STORE_ICON)}: must be 128x128 RGBA with a fully transparent 16px margin")
    return bad


def main():
    ap = argparse.ArgumentParser(description="トレひろ の Chrome ウェブストア用画像を合成して検査する。")
    ap.add_argument("--out-root", type=Path, default=ASSETS,
                    help="screenshots/ と promo/ を書き出すフォルダ（既定: store-assets/。上書き）")
    ap.add_argument("--browser", default=None, help="Chrome の実行ファイル（既定: 自動検出 / CHROME_PATH）")
    ap.add_argument("--font", default=None,
                    help='フォントファイル、または "hiragino"（既定: macOS は hiragino、Windows は NotoSansJP-VF.ttf）')
    ap.add_argument("--preview-dir", type=Path, default=None, help="640x400（タイルは半分）の縮小版も書く")
    ap.add_argument("--only", nargs="*", help="描き出すページ（例: 02-wide.html）")
    ap.add_argument("--tmp-dir", type=Path, default=None, help="一時ファイルの置き場所（既定: システムの一時フォルダ）")
    args = ap.parse_args()

    browser = cdp.find_chrome(args.browser)
    if not Path(browser).is_file():
        sys.exit(f"Chrome not found: {browser} (use --browser)")
    font_css, font_desc = make_font_css(args.font or default_font())
    print(f"  font: {font_desc}")
    print(f"  browser: {browser}")
    out_root = args.out_root.resolve()
    geom = prepare(font_css)
    for k, v in geom.items():
        print(f"  build/{k}.png  {v['w']}x{v['h']}  from {v['src']}")
    pages = [p for p in PAGES if not args.only or p[0] in args.only]
    if args.only and len(pages) != len(args.only):
        sys.exit(f"unknown page in --only: {sorted(set(args.only) - {p[0] for p in PAGES})}")
    t = time.time()
    problems = render(pages, out_root, browser, args.preview_dir, args.tmp_dir)
    bad = verify(out_root, pages)
    print(f"done in {time.time() - t:.1f}s")
    if problems or bad:
        print("FAILED:", *problems, *bad, sep="\n  ")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
