#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""トレひろのアイコン（16/48/128px）とストアアイコンを描き出して検査する。

Pillow と標準ライブラリだけで動く（numpy・Chrome は不要。Python 3.9 互換）。
乱数・日時・フォントを使わないので、同じ環境（Pillow と、Pillow が使う zlib の版が同じ）なら、
何度実行しても同じバイト列になる。

使い方（リポジトリのルートで実行）:

    python3 store-assets/tools/icon/render_icons.py
        次の 5 つを書き出して検査する。
          icons/icon16.png, icons/icon48.png, icons/icon128.png   … manifest の icons / action.default_icon
          store-assets/icon/store-icon-128.png                    … ストアアイコン（icons/icon128.png とバイト単位で同じ）
          store-assets/tools/icon/palette.json                    … 宣材・合成画像が使う色

    python3 store-assets/tools/icon/render_icons.py --out-root DIR
        同じフォルダ構成で DIR の下に書き出す（試し描き用）。

    python3 store-assets/tools/icon/render_icons.py --check
        書き出さずに、今あるファイルを検査する。スクリプトの出力とバイト単位で一致するかも確かめる
        （palette.json は改行コードの違いを無視して比べる。PNG は Pillow / zlib の版が違うと、
        画素が同じでもバイトが変わり、一致の検査だけが NG になることがある）。

    python3 store-assets/tools/icon/render_icons.py --preview PNG \\
            [--trello-favicon PNG] [--old-icons DIR] [--giga-icons DIR] [--giga-store PNG]
        社内確認用の見比べシートを PNG に書く（アイコンの書き出しはしない）。
        - 大きさと背景（16/32/48/128px を 白・#F1F2F4・#1F1F21、グレースケール）
        - タブ列とツールバーの再現（1x / 2x、ライト / ダーク）
        - 小さいサイズを密に並べた行（Trello のファビコン／旧アイコン／新アイコン／ギガひろ）
        - ぼかし＋グレースケール（目を細めて見たときの形）
        - ギガひろと並べた見え方
        比べる相手の画像は引数で渡す（--old-icons と --giga-icons は icon16/48/128.png のあるフォルダ）。
        Trello のファビコンが写るので、PNG はリポジトリの外にしか書けない。

検査（どれかに通らなければ終了コード 1）:
    - 大きさ・モード（RGBA）が正しい
    - icon128 とストアアイコン: 不透明な部分の範囲が (16, 16, 112, 112)、外側の 16px は完全に透明
      （CWS の画像ガイドライン: 96x96 のアートワーク＋各辺 16px の透明な余白）
    - icon48: タイルは 1〜47px（各辺 1px の透明余白）。icon16: 全面
    - ストアアイコンが icons/icon128.png とバイト単位で同じ
    - 彩度 0.3 以上の画素に、Atlassian / Trello の青（色相 200〜225°）が 1 つもない
    - もう一度描いた結果とバイト単位で一致する（決定的に描けている）

図柄（96x96 のアートワーク単位。128px では 1 単位 = 1px）:
    - 地: 角丸スクエアのタイル。#14B8A6 → #0F766E の縦グラデーション（ティール。色相 173〜175°）。
    - 白い横長のカード 1 枚（52x40）を、黄（#FBBF24）の区切り線で 6:4 に分ける（説明欄とコメント欄）。
      区切り線はカードの上下の縁から 4 単位内側で止めて、白いカードを 1 枚に保つ。
      （白が縦長の板 2 枚に分かれると、Trello のロゴ「白い縦の棒 2 本」に近づくため）
    - 区切り線の中央に黄のつまみ、カードの左右に白い山形 ‹ ›（広げる）。カードの下に濃いティールの影。
    - 48px は座標を偶数の単位（= 画素の境界）にそろえた版。山形は 2px の線。
    - 16px は画素の境界に合わせて描いた簡略版（12x8 のカード＋左の欄の見出し線＋x=9 の 1px の区切り線
      ＋3x4 のつまみ。山形なし）。区切り線の上下に白を 1px ずつ残し、カードを 1 枚に見せる。
    - ギガひろ（青いタイル＋白い時計＋黄の稲妻）と同じ「彩度の高いタイル＋白いモチーフ＋黄のアクセント」。

縮小の方法（8 倍の大きさで描いてから縮小する）:
    - 48/128px の色は LANCZOS で縮小する（輪郭がくっきりする）。
    - 透明度は、タイルの形だけを描いたマスクを BOX（面積平均）で縮小した値を使う。
      LANCZOS はリンギングで透明な余白に 1〜2/255 の不透明度を漏らすので、128px の
      「外側 16px は完全に透明」が崩れ、16px の縁にもにじみが出るため。
    - 色はタイルの外までグラデーションで塗っておき、形はマスクで切り抜く（縁が黒くにじまない）。
    - 16px は画素の境界に合わせて描いているので、色も BOX で縮小する（1px の線の両側に色を漏らさない）。
"""
import argparse
import colorsys
import hashlib
import io
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

SS = 8  # 描画の倍率（8 倍で描いて縮小する）

# 出力先（--out-root からの相対パス）
OUT_ICON = {16: "icons/icon16.png", 48: "icons/icon48.png", 128: "icons/icon128.png"}
OUT_STORE = "store-assets/icon/store-icon-128.png"
OUT_PALETTE = "store-assets/tools/icon/palette.json"

# 避ける色相（Atlassian / Trello の青。#0C66E4, #1558BC, #0052CC, #0079BF など）
FORBIDDEN_HUE = (200.0, 225.0)
FORBIDDEN_MIN_SAT = 0.3

# ---------------------------------------------------------------- 色
PALETTE = {
    "tile_top": "#14B8A6",     # タイル上端（teal-500。色相 173°）
    "tile_bottom": "#0F766E",  # タイル下端（teal-700。色相 175°）
    "tile_mid": "#12978A",     # グラデーションの中間（地を単色で塗るときの代表色）
    "shadow": "#0A4F49",       # カードの影（濃いティール）
    "white": "#FFFFFF",        # カード・山形
    "accent": "#FBBF24",       # 区切り線・つまみ（ギガひろと同じ黄。amber-400）
    "accent_edge": "#F59E0B",  # 黄の縁・16px の区切り線（amber-500）
    "ink": "#115E59",          # カード内の見出し線・つまみの溝（teal-800）
    "line": "#CFE3E0",         # カード内の本文線（淡いティールグレー）
}
# 宣材・合成画像のためだけの色（アイコンには使わない）
EXTRA = {
    "tile_deep": "#134E4A",    # 大きな背景のグラデーションの暗い端（teal-900）
    "tile_hi": "#2DD4BF",      # 背景の光（teal-400。半透明の放射グラデーションで使う）
    "on_tile_sub": "#CCFBF1",  # 地の上の小見出し・補足（teal-100）
}

# ---------------------------------------------------------------- 図柄の定義
# 128px 用（96 単位のアートワーク。1 単位 = 1px、16px の余白の内側に置く）
GEOM = {
    "tile": (0, 0, 96, 96),
    "tile_r": 24,                 # 角の半径（ギガひろのタイルに近い 1/4）
    "card": (22, 26, 74, 66),     # 52x40 の横長カード（1 枚）。上下の中央（白と地のコントラストが高い所）
    "card_r": 6,
    "shadow_dy": 4, "shadow_blur": 2.5, "shadow_alpha": 150,
    "div_x": (51, 55),            # 区切り線（中心 53 → カード 22〜74 を 31 : 21 ≒ 6:4 に分ける）
    "div_inset": 4,               # 区切り線を上下の縁から 4 単位離し、白いカードを 1 枚に保つ
    "grip": (48, 39, 58, 53),     # つまみ（区切り線の中央の縦長の角丸）
    "grip_r": None,               # None で両端を半円にする
    "grip_edge": 1.5,             # つまみの縁（amber-500）
    "grip_marks": "bars",         # つまみの溝: bars / none
    "chev_w": 6,                  # 山形の線の太さ
    "chev_l": [(16, 37), (10, 46), (16, 55)],   # 高さ 18。外側の端はタイルの縁から 7 単位
    "chev_r": [(80, 37), (86, 46), (80, 55)],
    "content": "full",            # カード内の線: full（128px） / lite（48px）
}

# 48px 用の上書き（1 単位 = 0.5px。座標を偶数の単位にそろえて画素の境界に乗せる）
GEOM48 = {
    "tile": (2, 2, 94, 94),       # タイルは 1〜47px（各辺 1px の透明余白。ギガひろの icon48 に近い）
    "tile_r": 22,                 # 11px
    "div_x": (52, 56),            # 26〜28px（カード 11〜37px を 15+1 : 9+1 ≒ 6:4）
    "grip": (48, 38, 60, 54),     # 6x8px の角丸
    "grip_r": 2.5,
    "grip_edge": 2,               # 縁 1px
    "grip_marks": "none",
    "chev_w": 4,                  # 2px の線。頂点と両端の中心を整数の画素に置く
    "chev_l": [(16, 36), (10, 46), (16, 56)],   # 頂点 (5, 23)px、両端 (8, 18) / (8, 28)px。高さ 10px
    "chev_r": [(80, 36), (86, 46), (80, 56)],   # タイルの縁から 3px、カードから 2px 離す（2x の 32px でも離れて見える）
    "content": "lite",
}

# 16px 用（1 単位 = 1px）
GEOM16 = {
    "tile_r": 3.5,
    "card": (2, 4, 14, 12),       # 白いカード: x 2〜13、y 4〜11（12x8px）
    "shadow": (3, 5, 13, 13),     # 影はカードの下の y=12 に 1 行だけ見える（両端を 1px ずつ縮める）
    "shadow_alpha": 52,           # 地と重ねて #0F7A70 前後（下線や台に見えない淡さ）
    "div": (9, 5, 10, 11),        # 区切り線 x=9 の 1px（左 7px : 右 4px）。上下 1px の白を残す
    "grip": (8, 6, 11, 10),       # つまみ 3x4px
    "ink_line": (3, 6, 7, 7),     # 左の欄の見出し線 x 3〜6、y=6（48/128px のカードと同じ「見出し」。白は 1 枚につながったまま）
}


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(h, a=255):
    return hex2rgb(h) + (a,)


class Canvas(object):
    """アートワーク単位 → 8 倍キャンバスの画素 へ変換して描く。"""

    def __init__(self, size, unit_px, offset_px):
        self.size = size
        self.k = unit_px * SS      # 1 単位あたりのキャンバス画素
        self.o = offset_px * SS
        self.rgb = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 255))
        self.mask = Image.new("L", (size * SS, size * SS), 0)

    def p(self, v):
        return self.o + v * self.k

    def box(self, b):
        # PIL の矩形は右下の画素を含むので 1 引く（8 倍なので 1/8px 未満の差）
        return [self.p(b[0]), self.p(b[1]), self.p(b[2]) - 1, self.p(b[3]) - 1]

    def layer(self):
        return Image.new("RGBA", self.rgb.size, (0, 0, 0, 0))

    def paste(self, lay):
        self.rgb = Image.alpha_composite(self.rgb, lay)

    def out(self, rgb_filter):
        rgb = self.rgb.convert("RGB").resize((self.size, self.size), rgb_filter)
        a = self.mask.resize((self.size, self.size), Image.BOX)
        im = rgb.convert("RGBA")
        im.putalpha(a)
        return im


def gradient_tile(cv, box, r, top, bottom):
    """縦グラデーションの角丸タイル。色はキャンバス全面に塗り（縁のにじみ防止）、形はマスクで持つ。"""
    w, h = cv.rgb.size
    gd = ImageDraw.Draw(cv.rgb)
    y0, y1 = cv.p(box[1]), cv.p(box[3])
    c0, c1 = hex2rgb(top), hex2rgb(bottom)
    for y in range(h):
        t = min(1.0, max(0.0, (y + 0.5 - y0) / float(y1 - y0)))
        c = tuple(int(round(c0[i] + (c1[i] - c0[i]) * t)) for i in range(3))
        gd.line([(0, y), (w, y)], fill=c + (255,))
    ImageDraw.Draw(cv.mask).rounded_rectangle(cv.box(box), radius=r * cv.k, fill=255)


def polyline(d, pts, width, fill):
    """丸い端・丸い角の折れ線（キャンバス画素で指定）。"""
    d.line(pts, fill=fill, width=int(round(width)), joint="curve")
    rr = width / 2.0
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=fill)


def pill(d, cv, b, fill, edge=0, edge_fill=None, r=None):
    """角丸の形（r を省くと短い辺の半分＝両端が半円）。edge>0 なら縁取りする。"""
    if r is None:
        r = min(b[2] - b[0], b[3] - b[1]) / 2.0
    if edge > 0:
        d.rounded_rectangle(cv.box(b), radius=r * cv.k, fill=edge_fill)
        b = (b[0] + edge, b[1] + edge, b[2] - edge, b[3] - edge)
        r = max(0.0, r - edge)
    d.rounded_rectangle(cv.box(b), radius=r * cv.k, fill=fill)


def draw_full(size, unit_px, offset_px, g):
    """48px と 128px 用。"""
    pal = PALETTE
    cv = Canvas(size, unit_px, offset_px)
    gradient_tile(cv, g["tile"], g["tile_r"], pal["tile_top"], pal["tile_bottom"])
    c = g["card"]

    # カードの影（下へずらしてぼかす）
    sh = cv.layer()
    sb = (c[0], c[1] + g["shadow_dy"], c[2], c[3] + g["shadow_dy"])
    ImageDraw.Draw(sh).rounded_rectangle(cv.box(sb), radius=g["card_r"] * cv.k,
                                         fill=rgba(pal["shadow"], g["shadow_alpha"]))
    sh = sh.filter(ImageFilter.GaussianBlur(g["shadow_blur"] * cv.k))
    cv.paste(sh)

    lay = cv.layer()
    d = ImageDraw.Draw(lay)
    # 白いカード（1 枚）
    d.rounded_rectangle(cv.box(c), radius=g["card_r"] * cv.k, fill=rgba(pal["white"]))

    x0, x1 = g["div_x"]
    if g["content"] == "full":
        # 左の欄（説明）: 見出し 1 本＋本文 4 本
        lx = c[0] + 6
        lw = x0 - 4 - lx
        for y, f, col, h in ((32, 0.6, "ink", 4), (40, 1, "line", 3), (46, 1, "line", 3),
                             (52, 1, "line", 3), (58, 0.7, "line", 3)):
            pill(d, cv, (lx, y, lx + round(lw * f), y + h), rgba(pal[col]))
        # 右の欄（コメント）: 丸いアバター＋線 を 2 組
        rx, rend = x1 + 5, c[2] - 5
        for y in (32, 47):
            d.ellipse(cv.box((rx, y, rx + 6, y + 6)), fill=rgba(pal["line"]))
            pill(d, cv, (rx, y + 8, rend, y + 11), rgba(pal["line"]))
    else:
        # 48px: 線は 2px（4 単位）で偶数の単位にそろえる。右の欄はアバターを省く（3px の丸はにじむため）
        lx = c[0] + 6
        lw = x0 - 4 - lx
        for y, f, col in ((32, 0.6, "ink"), (40, 1, "line"), (48, 1, "line"), (56, 0.7, "line")):
            pill(d, cv, (lx, y, lx + 2 * round(lw * f / 2), y + 4), rgba(pal[col]))
        rx, rend = x1 + 4, c[2] - 4
        for y, cut in ((32, 0), (40, 4), (48, 0), (56, 6)):
            pill(d, cv, (rx, y, rend - cut, y + 4), rgba(pal["line"]))

    # 区切り線（黄）。上下の縁から div_inset だけ内側で止める
    pill(d, cv, (x0, c[1] + g["div_inset"], x1, c[3] - g["div_inset"]), rgba(pal["accent"]))
    # つまみ
    gb = g["grip"]
    pill(d, cv, gb, rgba(pal["accent"]), g["grip_edge"], rgba(pal["accent_edge"]), g["grip_r"])
    if g["grip_marks"] == "bars":
        gx = (gb[0] + gb[2]) / 2.0
        gy = (gb[1] + gb[3]) / 2.0
        for dy in (-3, 3):
            pill(d, cv, (gx - 2.5, gy + dy - 1, gx + 2.5, gy + dy + 1), rgba(pal["ink"]))

    # 左右の山形（広げる）
    for key in ("chev_l", "chev_r"):
        pts = [(cv.p(x), cv.p(y)) for x, y in g[key]]
        polyline(d, pts, g["chev_w"] * cv.k, rgba(pal["white"]))
    cv.paste(lay)
    return cv.out(Image.LANCZOS)


def draw_16(g):
    """16px 用。画素の境界に合わせた簡略版（カード 12x8＋区切り線＋つまみ。山形は省く）。"""
    pal = PALETTE
    cv = Canvas(16, 1, 0)
    gradient_tile(cv, (0, 0, 16, 16), g["tile_r"], pal["tile_top"], pal["tile_bottom"])
    sh = cv.layer()
    ImageDraw.Draw(sh).rectangle(cv.box(g["shadow"]), fill=rgba(pal["shadow"], g["shadow_alpha"]))
    cv.paste(sh)
    lay = cv.layer()
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle(cv.box(g["card"]), radius=1.0 * SS, fill=rgba(pal["white"]))
    if g["ink_line"]:
        d.rectangle(cv.box(g["ink_line"]), fill=rgba(pal["ink"]))
    d.rectangle(cv.box(g["div"]), fill=rgba(pal["accent_edge"]))
    gx0, gy0, gx1, gy1 = g["grip"]
    d.rectangle(cv.box(g["grip"]), fill=rgba(pal["accent"]))
    d.rectangle(cv.box((g["div"][0], gy0, g["div"][2], gy1)), fill=rgba(pal["accent_edge"]))
    cv.paste(lay)
    return cv.out(Image.BOX)


def render_all():
    """{16: Image, 48: Image, 128: Image} を返す。"""
    return {
        16: draw_16(GEOM16),
        48: draw_full(48, 0.5, 0, dict(GEOM, **GEOM48)),
        128: draw_full(128, 1, 16, GEOM),
    }


def png_bytes(im):
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------- palette.json
def rel_lum(h):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = hex2rgb(h)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = rel_lum(a), rel_lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def palette_doc():
    p, e = PALETTE, EXTRA
    doc = {
        "name": "トレひろ ブランドカラー（新アイコンの色）",
        "source": "store-assets/tools/icon/render_icons.py が書き出す。手で直さず、スクリプトの PALETTE を直して再実行する。",
        # 代表色（宣材・合成画像はこのキーを使う）
        "tile": p["tile_mid"],
        "tile_light": p["tile_top"],
        "tile_dark": p["tile_bottom"],
        "tile_deep": e["tile_deep"],
        "tile_hi": e["tile_hi"],
        "accent": p["accent"],
        "accent_deep": p["accent_edge"],
        "on_tile": p["white"],
        "on_tile_sub": e["on_tile_sub"],
        "ink": p["ink"],
        # アイコンの描画に使った色そのもの
        "icon": dict(p),
        "gradients": {
            "icon_tile": "linear-gradient(180deg, %s 0%%, %s 100%%)" % (p["tile_top"], p["tile_bottom"]),
            "background": "linear-gradient(135deg, #0D9488 0%%, %s 48%%, %s 100%%)" % (p["tile_bottom"], e["tile_deep"]),
            "background_glow": ("radial-gradient(760px 520px at 86% -6%, rgba(45, 212, 191, 0.45), transparent 70%), "
                                "radial-gradient(640px 460px at -4% 108%, rgba(4, 47, 46, 0.6), transparent 70%)"),
            "background_css": ("radial-gradient(760px 520px at 86%% -6%%, rgba(45, 212, 191, 0.45), transparent 70%%), "
                               "radial-gradient(640px 460px at -4%% 108%%, rgba(4, 47, 46, 0.6), transparent 70%%), "
                               "linear-gradient(135deg, #0D9488 0%%, %s 48%%, %s 100%%)" % (p["tile_bottom"], e["tile_deep"])),
        },
        # CSS を使わない合成（Pillow など）向けの同じグラデーション。angle は CSS と同じ向き（0 = 上へ、時計回り）
        "gradient_stops": {
            "icon_tile": {"angle": 180, "stops": [[p["tile_top"], 0.0], [p["tile_bottom"], 1.0]]},
            "background": {"angle": 135, "stops": [["#0D9488", 0.0], [p["tile_bottom"], 0.48], [e["tile_deep"], 1.0]]},
        },
        "contrast_white_on": {
            p["tile_top"]: contrast("#FFFFFF", p["tile_top"]),
            p["tile_mid"]: contrast("#FFFFFF", p["tile_mid"]),
            "#0D9488": contrast("#FFFFFF", "#0D9488"),
            p["tile_bottom"]: contrast("#FFFFFF", p["tile_bottom"]),
            p["ink"]: contrast("#FFFFFF", p["ink"]),
            e["tile_deep"]: contrast("#FFFFFF", e["tile_deep"]),
        },
        "contrast_other": {
            "on_tile_sub on tile_dark": contrast(e["on_tile_sub"], p["tile_bottom"]),
            "on_tile_sub on tile_deep": contrast(e["on_tile_sub"], e["tile_deep"]),
            "ink on white": contrast(p["ink"], "#FFFFFF"),
            "accent on tile_deep": contrast(p["accent"], e["tile_deep"]),
        },
        "notes": [
            "地の色はアイコンのタイルと同じティール系（色相 172〜176°）。Atlassian / Trello の青（色相 200〜225°、#0C66E4・#1558BC・#0052CC・#0079BF など）は使わない。",
            "宣材・スクリーンショットの地は gradients.background_css（#0D9488 → tile_dark → tile_deep の 135° のグラデーションに、右上の光と左下の影を重ねたもの）。ギガひろの青い地（#2563eb → #1d4ed8 → #1e3a8a）と同じ組み立て。",
            "アイコンと同じ見た目が必要な小さな面（バッジ・タイル）は gradients.icon_tile（tile_light → tile_dark の縦グラデーション）。",
            "白い見出しは tile_dark 以下の暗い側に置く（白と tile_light は約 2.5:1 しかない）。大見出し（24px 以上・太字）は #0D9488 の上でも可（約 3.7:1）。",
            "小見出し・補足は on_tile_sub（#CCFBF1）。下端の注記（約 7:1）は tile_deep（白で約 9.5:1）か ink（白で約 7.6:1）の上に白で置く。",
            "強調（リング・矢印・引き出し線）は accent_deep（#F59E0B）、塗りの強調は accent（#FBBF24。ギガひろと同じ黄）。",
            "白いカード型のパネルの影は、黒ではなく濃いティール（icon.shadow #0A4F49、不透明度 25〜40%）。",
        ],
    }
    return doc


def palette_bytes():
    return (json.dumps(palette_doc(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# ---------------------------------------------------------------- 検査
def forbidden_hue_pixels(im):
    n = 0
    for r, g, b, a in im.getdata():
        if a == 0:
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if s >= FORBIDDEN_MIN_SAT and FORBIDDEN_HUE[0] <= h * 360.0 <= FORBIDDEN_HUE[1]:
            n += 1
    return n


def palette_forbidden(doc):
    bad = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and len(v) == 7 and v.startswith("#"):
            r, g, b = hex2rgb(v)
            h, s, _ = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if s >= FORBIDDEN_MIN_SAT and FORBIDDEN_HUE[0] <= h * 360.0 <= FORBIDDEN_HUE[1]:
                bad.append(v)
    walk(doc)
    return bad


def verify(root, expected=None):
    """root の下の出力を検査する。expected = {相対パス: bytes} があれば内容の一致も確かめる。"""
    problems = []
    lines = []

    def ok(cond, msg):
        lines.append(("OK  " if cond else "NG  ") + msg)
        if not cond:
            problems.append(msg)

    spec = [(OUT_ICON[16], 16, (0, 0, 16, 16)),
            (OUT_ICON[48], 48, (1, 1, 47, 47)),
            (OUT_ICON[128], 128, (16, 16, 112, 112)),
            (OUT_STORE, 128, (16, 16, 112, 112))]
    for rel, size, bbox in spec:
        path = os.path.join(root, rel)
        if not os.path.isfile(path):
            ok(False, "%s がない" % rel)
            continue
        with open(path, "rb") as f:
            data = f.read()
        im = Image.open(io.BytesIO(data))
        fmt, mode = im.format, im.mode
        im.load()
        ok(fmt == "PNG" and mode == "RGBA" and im.size == (size, size),
           "%s  %s %dx%d %s（期待: PNG %dx%d RGBA）" % (rel, fmt, im.size[0], im.size[1], mode, size, size))
        if mode != "RGBA":
            im = im.convert("RGBA")
        got = im.split()[3].getbbox()
        ok(got == bbox, "%s  不透明な部分の範囲 %s（期待: %s。外側の alpha はすべて 0）" % (rel, got, bbox))
        if size == 128:
            # アートワークが 96x96 をきちんと使っている（上下左右の辺の中央が不透明）
            a = im.split()[3]
            edges = [a.getpixel(p) for p in ((64, 16), (64, 111), (16, 64), (111, 64))]
            ok(min(edges) == 255, "%s  96x96 のアートワークの辺の中央が不透明 %s" % (rel, edges))
        n = forbidden_hue_pixels(im)
        ok(n == 0, "%s  色相 %d〜%d°（彩度 %.1f 以上）の画素 %d 個" % (rel, FORBIDDEN_HUE[0], FORBIDDEN_HUE[1],
                                                                 FORBIDDEN_MIN_SAT, n))
        if expected is not None and rel in expected:
            ok(data == expected[rel], "%s  もう一度描いた結果とバイト単位で一致" % rel)
        lines.append("    md5 %s  %d bytes" % (hashlib.md5(data).hexdigest(), len(data)))

    a_path, b_path = os.path.join(root, OUT_ICON[128]), os.path.join(root, OUT_STORE)
    if os.path.isfile(a_path) and os.path.isfile(b_path):
        with open(a_path, "rb") as fa, open(b_path, "rb") as fb:
            ok(fa.read() == fb.read(), "%s と %s がバイト単位で同じ" % (OUT_STORE, OUT_ICON[128]))

    ppath = os.path.join(root, OUT_PALETTE)
    if not os.path.isfile(ppath):
        ok(False, "%s がない" % OUT_PALETTE)
    else:
        with open(ppath, "rb") as f:
            pdata = f.read()
        try:
            doc = json.loads(pdata.decode("utf-8"))
        except ValueError as ex:
            ok(False, "%s を JSON として読めない: %s" % (OUT_PALETTE, ex))
            doc = None
        if doc is not None:
            need = ("tile", "tile_light", "tile_dark", "accent", "accent_deep", "on_tile", "gradients")
            miss = [k for k in need if k not in doc]
            ok(not miss, "%s  必要なキー %s" % (OUT_PALETTE, "がそろっている" if not miss else "が足りない: %s" % miss))
            bad = palette_forbidden(doc)
            ok(not bad, "%s  色相 %d〜%d° の色 %s" % (OUT_PALETTE, FORBIDDEN_HUE[0], FORBIDDEN_HUE[1], bad or "なし"))
            if expected is not None and OUT_PALETTE in expected:
                # Windows の Git の既定（core.autocrlf=true）で CRLF になっていても、中身が同じなら一致とみなす
                ok(pdata.replace(b"\r\n", b"\n") == expected[OUT_PALETTE], "%s  スクリプトの出力と一致" % OUT_PALETTE)
    return problems, lines


# ---------------------------------------------------------------- 見比べシート（社内確認用）
FONT_PATHS = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
]
FONT_BOLD_PATHS = ["/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "C:/Windows/Fonts/meiryob.ttc"] + FONT_PATHS
_font_cache = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        f = None
        for path in (FONT_BOLD_PATHS if bold else FONT_PATHS):
            if os.path.exists(path):
                f = ImageFont.truetype(path, size)
                break
        _font_cache[key] = f or ImageFont.load_default()
    return _font_cache[key]


def text(d, xy, s, size=14, fill=(41, 42, 46), bold=False, anchor="la"):
    d.text(xy, s, font=font(size, bold), fill=fill, anchor=anchor)


def at(im, size):
    """表示用の縮小（ブラウザが大きいアイコンを縮めるのと同じく、乗算済みアルファで LANCZOS）。"""
    if im.size == (size, size):
        return im
    return im.convert("RGBa").resize((size, size), Image.LANCZOS).convert("RGBA")


def gray(im):
    g = ImageOps.grayscale(im.convert("RGB")).convert("RGBA")
    g.putalpha(im.split()[3])
    return g


def zoom(im, k):
    return im.resize((im.size[0] * k, im.size[1] * k), Image.NEAREST)


def load_png(path):
    if path and os.path.isfile(path):
        return Image.open(path).convert("RGBA")
    return None


def placeholder(size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, size - 1, size - 1], outline=(200, 40, 160, 255), width=max(1, size // 16))
    d.line([0, 0, size - 1, size - 1], fill=(200, 40, 160, 255), width=max(1, size // 16))
    return im


class IconSet(object):
    """表示する大きさごとに、拡張が実際に使う画像を選ぶ（16 は icon16、32 は icon48 を縮小、など）。"""

    def __init__(self, name, by_size):
        self.name = name
        self.by = dict((k, v) for k, v in by_size.items() if v is not None)

    def get(self, size):
        if not self.by:
            return placeholder(size)
        if size in self.by:
            return self.by[size]
        bigger = sorted(s for s in self.by if s >= size)
        src = self.by[bigger[0]] if bigger else self.by[max(self.by)]
        return at(src, size)


def icon_dir_set(name, d):
    if not d:
        return IconSet(name, {})
    return IconSet(name, dict((s, load_png(os.path.join(d, "icon%d.png" % s))) for s in (16, 48, 128)))


def on_bg(im, bg):
    base = Image.new("RGBA", im.size, bg + (255,))
    base.alpha_composite(im)
    return base


def browser_strip(scale, dark, favicon, ext_icons, title):
    """Chrome のタブ列＋ツールバーをごく簡単に再現する（scale=2 は高解像度の画面）。"""
    s = scale
    W, H = 296 * s, 76 * s
    if dark:
        frame, tab, omni, fg, sub = (31, 31, 33), (53, 54, 58), (32, 33, 36), (232, 234, 237), (154, 160, 166)
    else:
        frame, tab, omni, fg, sub = (223, 225, 229), (255, 255, 255), (241, 243, 244), (32, 33, 36), (95, 99, 104)
    im = Image.new("RGBA", (W, H), frame + (255,))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([8 * s, 6 * s, 176 * s, 40 * s], radius=8 * s, fill=tab + (255,))
    d.rectangle([8 * s, 30 * s, 176 * s, 40 * s], fill=tab + (255,))
    im.alpha_composite(favicon, (18 * s, 15 * s))
    text(d, (42 * s, 23 * s), title, 12 * s, fill=fg, anchor="lm")
    text(d, (196 * s, 23 * s), "新しいタブ", 12 * s, fill=sub, anchor="lm")
    d.rectangle([0, 40 * s, W, H], fill=tab + (255,))
    n = len(ext_icons)
    d.rounded_rectangle([10 * s, 46 * s, W - 14 * s - 28 * s * n, 70 * s], radius=12 * s, fill=omni + (255,))
    text(d, (24 * s, 58 * s), "trello.com/b/…", 12 * s, fill=sub, anchor="lm")
    x = W - 8 * s - 28 * s * n
    for icon in ext_icons:
        im.alpha_composite(icon, (x + 6 * s, 50 * s))
        x += 28 * s
    return im


def squint_cell(icon, bg, show, mode, cell):
    """目を細めて見たときの形: 背景に重ねた実寸のアイコンを show px に拡大し、ぼかし・グレースケールにする。"""
    base = on_bg(icon, bg).convert("RGB")
    big = base.resize((show, show), Image.BICUBIC)
    if "blur" in mode:
        big = big.filter(ImageFilter.GaussianBlur(3.5))
    if "gray" in mode:
        big = ImageOps.grayscale(big).convert("RGB")
    out = Image.new("RGB", (cell, cell), bg)
    out.paste(big, ((cell - big.size[0]) // 2, (cell - big.size[1]) // 2))
    return out.convert("RGBA")


def render_preview(icons, path, refs):
    WHITE, LIGHT, DARK = (255, 255, 255), (241, 242, 244), (31, 31, 33)
    new = IconSet("新アイコン", icons)
    trello = IconSet("Trello", {256: refs.get("trello")} if refs.get("trello") is not None else {})
    old, giga = refs["old"], refs["giga"]
    giga_store = refs.get("giga_store")

    W = 1280
    sheet = Image.new("RGBA", (W, 4000), WHITE + (255,))
    d = ImageDraw.Draw(sheet)
    MUTED = (95, 99, 104)

    def fg_for(bg):
        return (230, 230, 232) if bg[0] < 100 else (41, 42, 46)

    y = 22
    text(d, (24, y), "トレひろ 新アイコン（最終版）— 横長カード＋6:4 の区切り線（黄）＋左右の山形", 24, bold=True)
    y += 40
    text(d, (24, y), "タイル %s → %s（縦グラデーション）／黄 %s・%s／128px とストアアイコンは 96x96 のアートワーク＋各辺 16px の透明余白／48px は各辺 1px の余白"
         % (PALETTE["tile_top"], PALETTE["tile_bottom"], PALETTE["accent"], PALETTE["accent_edge"]), 14, fill=MUTED)
    y += 40

    # 1. 大きさと背景
    text(d, (24, y), "1. 大きさと背景（16px・32px＝2x のツールバーで icon48 を縮小・48px・128px）", 17, bold=True)
    y += 32
    sizes = [("16px", 16), ("32px（2x）", 32), ("48px", 48), ("128px", 128)]
    for is_gray in (False, True):
        x = 24
        for name, bg in (("白 #FFFFFF", WHITE), ("#F1F2F4", LIGHT), ("#1F1F21（ダーク）", DARK)):
            fg = fg_for(bg)
            d.rounded_rectangle([x, y, x + 400, y + 196], radius=10, fill=bg + (255,), outline=(220, 221, 224))
            text(d, (x + 14, y + 10), name + ("・グレースケール" if is_gray else ""), 13, fill=fg, bold=True)
            base = y + 166
            xx = x + 16
            for label, s in sizes:
                im = new.get(s)
                if is_gray:
                    im = gray(im)
                sheet.alpha_composite(im, (xx, base - s))
                text(d, (xx, base + 8), label, 11, fill=fg)
                xx += max(s, 52) + 26
            x += 412
        y += 210
    # 拡大
    x = 24
    d.rounded_rectangle([x, y, W - 24, y + 258], radius=10, fill=LIGHT + (255,), outline=(220, 221, 224))
    text(d, (x + 14, y + 10), "拡大（画素の見え方。16px を 8 倍・48px を 4 倍・32px を 4 倍）", 13, bold=True)
    xx, base = x + 16, y + 228
    for im, k, label in ((new.get(16), 8, "16px ×8"), (gray(new.get(16)), 8, "16px ×8 グレー"),
                         (new.get(48), 4, "48px ×4"), (gray(new.get(48)), 4, "48px ×4 グレー"),
                         (new.get(32), 4, "32px（2x）×4")):
        z = zoom(im, k)
        sheet.alpha_composite(z, (xx, base - z.size[1]))
        text(d, (xx, base + 6), label, 11, fill=(41, 42, 46))
        xx += z.size[0] + 28
    y += 276

    # 2. タブ列とツールバー
    text(d, (24, y), "2. タブ列とツールバー（タブのファビコン = Trello。右端の拡張アイコン = 左: トレひろ、右: ギガひろ）", 17, bold=True)
    y += 32
    for scale in (1, 2):
        cells = []
        for dark in (False, True):
            for label, s in (("旧アイコン", old), ("新アイコン", new)):
                strip = browser_strip(scale, dark, trello.get(16 * scale), [s.get(16 * scale), giga.get(16 * scale)],
                                      "ボード | Trello")
                cells.append(("%s・%s・%dx" % (label, "ダーク" if dark else "ライト", scale), strip))
        per_row = 4 if scale == 1 else 2
        for k in range(0, len(cells), per_row):
            x = 24
            hmax = 0
            for label, strip in cells[k:k + per_row]:
                text(d, (x, y), label, 12, fill=MUTED)
                sheet.alpha_composite(strip, (x, y + 18))
                x += strip.size[0] + 12
                hmax = max(hmax, strip.size[1])
            y += 18 + hmax + 12
    y += 8

    # 3. 小さいサイズを密に並べる
    text(d, (24, y), "3. 小さいサイズを密に並べる（左半分 16px・右半分 32px。各組 左: カラー、右: グレースケール）",
         17, bold=True)
    y += 30
    sets = [trello, old, new, giga]
    for bg in (WHITE, LIGHT, DARK):
        d.rectangle([24, y, W - 24, y + 56], fill=bg + (255,), outline=(220, 221, 224))
        x = 40
        for s in (16, 32):
            for st in sets:
                im = st.get(s)
                yy = y + (56 - s) // 2
                sheet.alpha_composite(im, (x, yy))
                sheet.alpha_composite(gray(im), (x + s + 4, yy))
                x += 2 * s + 4 + (14 if s == 16 else 18)
            x += 40
        y += 56
    text(d, (40, y + 6), "並びは 16px・32px とも 左から " + "／".join(st.name for st in sets), 11, fill=MUTED)
    y += 34

    # 4. ぼかし＋グレースケール
    text(d, (24, y), "4. 目を細めて見たときの形（実寸の 16px・32px を背景に重ねて 56px に拡大 → カラー／グレー／ぼかし／ぼかし＋グレー）",
         17, bold=True)
    y += 30
    cell = 64
    modes = [("カラー", ""), ("グレー", "gray"), ("ぼかし", "blur"), ("ぼかし\n＋グレー", "blur gray")]
    x0 = 24
    for bg in (WHITE, DARK):
        d.rectangle([x0, y, x0 + 608, y + 24 + cell * 4 + 8], fill=bg + (255,), outline=(220, 221, 224))
        fg = fg_for(bg)
        xx = x0 + 70
        for s in (16, 32):
            for st in sets:
                text(d, (xx + cell // 2, y + 6), "%s %d" % (st.name.replace("アイコン", ""), s), 10, fill=fg, anchor="ma")
                for r, (mname, mode) in enumerate(modes):
                    sheet.alpha_composite(squint_cell(st.get(s), bg, 56, mode, cell), (xx, y + 24 + r * cell))
                xx += cell + 2
            xx += 4
        for r, (mname, mode) in enumerate(modes):
            d.multiline_text((x0 + 10, y + 24 + r * cell + cell // 2), mname, font=font(11), fill=fg, anchor="lm",
                             spacing=2)
        x0 += 624
    y += 24 + cell * 4 + 8 + 20

    # 5. ギガひろと並べる
    text(d, (24, y), "5. ギガひろと並べる（各組 左: ギガひろ、右: トレひろ。上: ストアアイコン 128px、下: 48px・16px）", 17, bold=True)
    y += 30
    x = 24
    for bg in (WHITE, LIGHT, DARK):
        d.rounded_rectangle([x, y, x + 400, y + 236], radius=10, fill=bg + (255,), outline=(220, 221, 224))
        g128 = giga_store if giga_store is not None else giga.get(128)
        sheet.alpha_composite(g128, (x + 56, y + 10))
        sheet.alpha_composite(new.get(128), (x + 216, y + 10))
        sheet.alpha_composite(giga.get(48), (x + 96, y + 160))
        sheet.alpha_composite(new.get(48), (x + 256, y + 160))
        sheet.alpha_composite(giga.get(16), (x + 160, y + 176))
        sheet.alpha_composite(new.get(16), (x + 320, y + 176))
        x += 412
    y += 252

    notes = [
        "Trello のファビコンは比べるためだけに使っている（社内確認用。配布しない・リポジトリに入れない）。",
        "旧アイコン = v2.0.1 の icons/。32px は Chrome の 2x 表示で icon48 を縮めたときの見え方（新・旧・ギガひろとも同じ扱い）。",
        "render_icons.py --preview で生成（Pillow のみ。8 倍で描いて縮小）。",
    ]
    for n in notes:
        text(d, (24, y), n, 12, fill=MUTED)
        y += 20
    sheet = sheet.crop((0, 0, W, y + 14))
    sheet.convert("RGB").save(path, optimize=True)


# ---------------------------------------------------------------- 実行
def inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def main(argv=None):
    ap = argparse.ArgumentParser(description="トレひろのアイコンとストアアイコンを描き出して検査する。")
    ap.add_argument("--out-root", default=REPO,
                    help="書き出し先のルート（既定: このリポジトリ）。icons/ と store-assets/ をこの下に作る")
    ap.add_argument("--check", action="store_true", help="書き出さずに、今あるファイルを検査だけする")
    ap.add_argument("--preview", metavar="PNG", help="社内確認用の見比べシートを書く（リポジトリの外に限る）")
    ap.add_argument("--trello-favicon", metavar="PNG", help="見比べに使う Trello のファビコン（--preview 用）")
    ap.add_argument("--old-icons", metavar="DIR", help="旧アイコンの icon16/48/128.png があるフォルダ（--preview 用）")
    ap.add_argument("--giga-icons", metavar="DIR", help="ギガひろの icon16/48/128.png があるフォルダ（--preview 用）")
    ap.add_argument("--giga-store", metavar="PNG", help="ギガひろのストアアイコン（--preview 用）")
    a = ap.parse_args(argv)

    icons = render_all()

    if a.preview:
        if inside(a.preview, REPO) or inside(a.preview, a.out_root):
            print("NG  見比べシートはリポジトリ（%s）の外に書いてください: %s" % (REPO, a.preview))
            return 1
        refs = {
            "trello": load_png(a.trello_favicon),
            "old": icon_dir_set("旧アイコン", a.old_icons),
            "giga": icon_dir_set("ギガひろ", a.giga_icons),
            "giga_store": load_png(a.giga_store),
        }
        for label, v in (("--trello-favicon", a.trello_favicon), ("--old-icons", a.old_icons),
                         ("--giga-icons", a.giga_icons), ("--giga-store", a.giga_store)):
            if not v:
                print("注意: %s を指定していないので、その欄は空の枠になります" % label)
        parent = os.path.dirname(os.path.abspath(a.preview))
        if not os.path.isdir(parent):
            os.makedirs(parent)
        render_preview(icons, a.preview, refs)
        print("見比べシート: %s" % a.preview)
        return 0

    expected = {OUT_ICON[s]: png_bytes(im) for s, im in icons.items()}
    expected[OUT_STORE] = expected[OUT_ICON[128]]
    expected[OUT_PALETTE] = palette_bytes()

    root = os.path.abspath(a.out_root)
    if not a.check:
        for rel, data in sorted(expected.items()):
            path = os.path.join(root, rel)
            parent = os.path.dirname(path)
            if not os.path.isdir(parent):
                os.makedirs(parent)
            with open(path, "wb") as f:
                f.write(data)
            print("書き出し: %s" % rel)

    # もう一度描いて、書き出したもの（--check では今あるもの）と比べる
    again = {OUT_ICON[s]: png_bytes(im) for s, im in render_all().items()}
    again[OUT_STORE] = again[OUT_ICON[128]]
    again[OUT_PALETTE] = palette_bytes()
    problems, lines = verify(root, again)
    print("検査（%s）:" % root)
    for line in lines:
        print("  " + line)
    if problems:
        print("NG  %d 件の問題があります" % len(problems))
        return 1
    print("OK  すべての検査に通りました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
