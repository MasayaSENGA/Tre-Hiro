"""トレひろ（Tre-Hiro）の Chrome ウェブストア用スクリーンショットの素材（未加工）を撮る。

    python3 store-assets/tools/capture_raw.py                         # すべて撮る
    python3 store-assets/tools/capture_raw.py --only card_default,popup_default
    python3 store-assets/tools/capture_raw.py --headed                # ブラウザの画面を出して撮る
    python3 store-assets/tools/capture_raw.py --browser "C:\\...\\chrome.exe" --out somewhere
    python3 store-assets/tools/capture_raw.py --profile-dir DIR       # 一時プロファイルを DIR に作る（終了後も残る）

しくみ:
    1. 新しい一時プロファイルで Chrome をヘッドレス起動する（--remote-debugging-pipe と
       --enable-unsafe-extension-debugging。ブラウザの場所は macOS / Windows / Linux で自動判定し、
       --browser で上書きできる）。
    2. 撮影用のタブでは CDP の Fetch ドメインですべてのリクエストを横取りする。
       https://trello.com/b/... と /c/... には tools/mock/ の再現ページ（自作の HTML/CSS/JS）を返し、
       それ以外はすべて失敗させる（外部へは一切通信しない。件数と URL を manifest.json に残す）。
       さらに Chrome 自体の名前解決を止めているので、横取りの外の通信も外へは出ない。
    3. まず拡張を入れない状態で再現ページを開き、Trello 標準の幅（1080 / 620 / 460）と、
       拡張の印（html[data-twc-on]）が無いことを記録する（対照）。
    4. CDP の Extensions.loadUnpacked でリポジトリ（本物のトレひろ）を読み込む。manifest の
       content_scripts.matches どおりに本物のコンテンツスクリプトが再現ページへ注入される。
    5. 本物のポップアップ（chrome-extension://<id>/popup.html）を別タブで開き、利用者と同じように
       スイッチをクリックし、スライダーに値を入れて input を発火させて設定を保存する。
       設定は chrome.storage.sync → storage.onChanged の本来の経路で、開いている再現ページに反映される。
    6. 撮る前に、再現ページが期待どおりの状態になったこと（html[data-twc-on] の有無、--twc-* 変数、
       塗られたカードの枚数＝ラベル付きカードの枚数、フォントの読み込み完了）を待って確かめる。
       カード詳細では、自動化ボタンの列（拡張が「自動化」の一覧を見えない状態で開いて読み、閉じた後に並ぶ）が
       設定どおり並んでいること（OFF なら無いこと）と、一覧が閉じていることも待つ。
    7. card_off_auto だけは、下部のナビの「自動化」を本物のクリックで開き、一覧が見えている状態で撮って閉じる。

出力: store-assets/raw/*.png（既定は 1440x900、deviceScaleFactor 2）と store-assets/raw/manifest.json
      （ファイル名は後工程の合成との約束。--only で一部だけ撮り直すと manifest.json は差し替えで更新する）

安全: ログイン・フォーム送信・同意のクリックはしない。触るのは自作の再現ページと拡張のポップアップだけ。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import time

from PIL import Image

sys.dont_write_bytecode = True   # tools/ に __pycache__ を作らない
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp  # noqa: E402

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(TOOLS_DIR, "..", ".."))
MOCK_DIR = os.path.join(TOOLS_DIR, "mock")
DEFAULT_OUT = os.path.join(REPO, "store-assets", "raw")

BOARD_URL = "https://trello.com/b/Mk7Wb2Qa/web-renewal"
CARD_URL = "https://trello.com/c/Hr8dT0pK/14-top-page-design"

DPR = 2
POPUP_VIEW = (300, 800)   # ポップアップは本来の幅 300px のまま（body だけを切り出す）

# shared.js の TWC_DEFAULTS と同じ（ポップアップの「既定値に戻す」で保存される値）
DEFAULTS = {"enabled": True, "cardWidth": 95, "descRatio": 60, "colorCards": True, "colorStrength": 16,
            "autoButtons": True}
# 再現ページのナビ「自動化」の一覧にあるカードボタンの数（mock.js の CARD_BUTTONS）
AUTO_BUTTONS = 6


def S(**kw) -> dict:
    d = dict(DEFAULTS)
    d.update(kw)
    return d


# 撮る順番どおりに並べる（設定の切り替えが少なくなる順）。name がファイル名（.png）になる。
SHOTS = [
    dict(name="popup_default", page="popup", settings=S(),
         desc="ポップアップ（既定: ON・幅 95%・比率 60:40・色付け ON・濃さ 16%）"),
    dict(name="card_default", page="card", view=(1440, 900), settings=S(), comments="open",
         desc="カード詳細（トレひろ ON・幅 95%・比率 60:40・コメント欄を開いた状態）"),
    dict(name="card_r75", page="card", view=(1440, 900), settings=S(descRatio=75), comments="open",
         desc="カード詳細（トレひろ ON・幅 95%・比率 75:25）"),
    dict(name="popup_r75", page="popup", settings=S(descRatio=75),
         desc="ポップアップ（比率 75:25）"),
    dict(name="card_r35", page="card", view=(1440, 900), settings=S(descRatio=35), comments="open",
         desc="カード詳細（トレひろ ON・幅 95%・比率 35:65）"),
    dict(name="popup_r35", page="popup", settings=S(descRatio=35),
         desc="ポップアップ（比率 35:65）"),
    dict(name="card_closed", page="card", view=(1440, 900), settings=S(), comments="closed",
         desc="カード詳細（トレひろ ON・幅 95%・コメント欄を閉じた状態＝説明欄が全幅）"),
    dict(name="card_off_closed", page="card", view=(1440, 900), settings=S(enabled=False), comments="closed",
         desc="カード詳細（トレひろ OFF＝Trello 標準・コメント欄を閉じた状態、幅 584px）"),
    dict(name="popup_off", page="popup", settings=S(enabled=False),
         desc="ポップアップ（メインスイッチ OFF）"),
    dict(name="card_off", page="card", view=(1440, 900), settings=S(enabled=False), comments="open",
         desc="カード詳細（トレひろ OFF＝Trello 標準・コメント欄を開いた状態、幅 1080px）"),
    dict(name="card_off_auto", page="card", view=(1440, 900), settings=S(enabled=False), comments="open",
         automation="open",
         desc="カード詳細（トレひろ OFF＝Trello 標準・下部のナビの「自動化」を押してカードボタンの一覧を開いた状態）"),
    dict(name="card_off_1280", page="card", view=(1280, 800), settings=S(enabled=False), comments="open",
         desc="カード詳細 1280x800（トレひろ OFF＝Trello 標準・コメント欄を開いた状態）"),
    dict(name="card_default_1280", page="card", view=(1280, 800), settings=S(), comments="open",
         desc="カード詳細 1280x800（トレひろ ON・幅 95%・比率 60:40）"),
    dict(name="board_color", page="board", view=(1440, 900), settings=S(),
         desc="ボード（トレひろ ON・カードの色付け ON・濃さ 16%）"),
    dict(name="board_color28", page="board", view=(1440, 900), settings=S(colorStrength=28),
         desc="ボード（トレひろ ON・カードの色付け ON・濃さ 28%）"),
    dict(name="popup_color28", page="popup", settings=S(colorStrength=28),
         desc="ポップアップ（カードの色付け 濃さ 28%）"),
    dict(name="board_off", page="board", view=(1440, 900), settings=S(colorCards=False),
         desc="ボード（トレひろ ON・カードの色付け OFF＝Trello 標準のカード）"),
]

log: dict = {"notes": [], "shots": []}


def note(msg: str):
    print(msg)
    log["notes"].append(msg)


def redact_home(text: str) -> str:
    """記録する文字列の中のホームフォルダ（ユーザー名を含むパス）を「~」に置き換える。

    ユーザー単位でインストールした Chrome（Windows の %LOCALAPPDATA%、macOS の ~/Applications）や
    --browser / CHROME_PATH で指定した場所を、ユーザー名ごと manifest.json に残さないため。
    """
    homes = {os.path.expanduser("~"), os.environ.get("USERPROFILE", "")}
    flags = re.IGNORECASE if os.name == "nt" else 0
    for home in sorted((h.rstrip("\\/") for h in homes if h and h != "~"), key=len, reverse=True):
        if home:
            text = re.sub(re.escape(home) + r"(?=[\\/]|$)", "~", text, flags=flags)
    return text


# ---------------------------------------------------------------------------
# 計測用の JS
# ---------------------------------------------------------------------------
JS_HELPERS = r"""
const R = (e) => { if (!e) return null; const r = e.getBoundingClientRect();
  return {x: +r.x.toFixed(2), y: +r.y.toFixed(2), width: +r.width.toFixed(2), height: +r.height.toFixed(2)}; };
const clip = (r, ...cs) => { if (!r) return null; let x0 = r.x, y0 = r.y, x1 = r.x + r.width, y1 = r.y + r.height;
  for (const c of cs) { if (!c) continue; x0 = Math.max(x0, c.x); y0 = Math.max(y0, c.y);
    x1 = Math.min(x1, c.x + c.width); y1 = Math.min(y1, c.y + c.height); }
  if (x1 <= x0 || y1 <= y0) return null;
  return {x: +x0.toFixed(2), y: +y0.toFixed(2), width: +(x1 - x0).toFixed(2), height: +(y1 - y0).toFixed(2)}; };
const VP = {x: 0, y: 0, width: innerWidth, height: innerHeight};
const html = document.documentElement;
const twc = () => ({
  on: html.hasAttribute('data-twc-on'), color: html.hasAttribute('data-twc-color'),
  vars: Object.fromEntries(['--twc-card-width', '--twc-card-max-width', '--twc-desc-ratio', '--twc-color-strength']
    .map(k => [k, html.style.getPropertyValue(k).trim()]))});
const boardCards = () => [...document.querySelectorAll('li[data-testid="list-card"]')].map(li => {
  const card = li.querySelector('[data-testid="trello-card"]');
  const painted = li.querySelector('[data-twc-card-color]');
  return {name: li.querySelector('a[data-testid="card-name"]').textContent.trim(),
    list: li.closest('[data-testid="list"]').querySelector('[data-testid="list-name"]').textContent.trim(),
    labels: [...li.querySelectorAll('button[data-testid="compact-card-label"]')].map(b => ({color: b.dataset.color, name: b.textContent.trim()})),
    painted: !!painted, paint_colors: painted ? painted.getAttribute('data-twc-card-color') : null,
    painted_element: painted ? (painted === card ? 'trello-card' : painted.parentElement === card ? 'trello-card > div' :
      painted.parentElement && painted.parentElement.parentElement === card ? 'trello-card > div > div' : painted.tagName) : null,
    rect: R(card), visible: clip(R(card), VP)};
});
const counts = () => { const cs = boardCards();
  return {cards: cs.length, labeled_cards: cs.filter(c => c.labels.length).length,
          painted_cards: document.querySelectorAll('[data-twc-card-color]').length}; };
const autoToggle = () => document.querySelector('nav.cb-nav button[aria-label="自動化"]');
const autoPopover = () => document.querySelector('.atlaskit-portal section[role="dialog"]');
const auto = () => { const t = autoToggle(), p = autoPopover();
  return {bar: !!document.querySelector('[data-twc-auto-bar]'),
          buttons: [...document.querySelectorAll('[data-twc-auto-bar] .twc-auto-btn')].map(b => b.textContent.trim()),
          busy: html.hasAttribute('data-twc-auto-busy') || !!document.querySelector('[data-twc-auto-hidden]'),
          pressed: t ? t.getAttribute('aria-pressed') : null,
          popover_items: p ? p.querySelectorAll('ul > li > button').length : 0,
          popover_opacity: p ? getComputedStyle(p).opacity : null}; };
"""

STATE_JS = "(() => {" + JS_HELPERS + r"""
  const btn = document.querySelector('[data-testid="card-back-activity-button"]');
  return {twc: twc(), counts: counts(), comments: btn ? btn.getAttribute('aria-checked') : null,
          auto: auto(), fonts: document.fonts.status, ready: document.readyState};
})()"""

CARD_MEASURE_JS = "(() => {" + JS_HELPERS + r"""
  const q = (s) => document.querySelector(s);
  const dialog = q('div[role="dialog"][data-testid="card-back-name"]');
  const main = dialog.querySelector('main'), aside = dialog.querySelector('aside');
  const D = R(dialog), M = R(main), A = R(aside);
  const inMain = (e) => ({rect: R(e), visible: clip(R(e), M, D, VP)});
  const inAside = (e) => ({rect: R(e), visible: clip(R(e), A, D, VP)});
  const btn = dialog.querySelector('[data-testid="card-back-activity-button"]');
  const open = btn.getAttribute('aria-checked') === 'true';
  const asideVisible = clip(A, D, VP);
  const cs = getComputedStyle;
  const actions = [...aside.querySelectorAll('li[data-testid="card-back-action"]')].map(li => Object.assign(
    {who: li.querySelector('.who').textContent.trim(), kind: li.querySelector('[data-testid="comment-container"]') ? 'comment' : 'activity'},
    inAside(li)));
  return {
    twc: twc(), counts: counts(), comments_open: open,
    widths: {dialog: D.width, main: M.width, aside: A.width, aside_visible: asideVisible ? asideVisible.width : 0,
             main_div: R(main.querySelector(':scope > div')).width, hgroup: R(main.querySelector('hgroup')).width,
             description: R(q('[data-testid="description-content-area"]')).width,
             table: R(q('.pm-table-container table')).width,
             ratio: open ? +(M.width / (M.width + A.width)).toFixed(4) : null},
    computed: {dialog_width: cs(dialog).width, dialog_max_width: cs(dialog).maxWidth, main_flex: cs(main).flex,
               main_min_width: cs(main).minWidth, aside_flex: cs(aside).flex, aside_width: cs(aside).width,
               aside_min_width: cs(aside).minWidth, aside_transform: cs(aside).transform,
               main_div_max_width: cs(main.querySelector(':scope > div')).maxWidth,
               hgroup_max_width: cs(main.querySelector('hgroup')).maxWidth},
    table_rows: [...q('.pm-table-container table').rows].map(r => +r.getBoundingClientRect().height.toFixed(2)),
    rects: {
      viewport: VP, dialog: D, dialog_header: R(dialog.querySelector('header')), main: M, aside: A,
      aside_visible: asideVisible,
      title: inMain(main.querySelector('section[data-testid="card-back-header"] hgroup')),
      quick_actions: inMain(q('.cb-quick-actions')),
      meta: inMain(q('.cb-meta')),
      description: inMain(q('section[data-testid="card-back-description"]')),
      description_body: inMain(q('[data-testid="description-content-area"]')),
      table: inMain(q('.pm-table-container table')),
      checklist: inMain(q('section[data-testid="checklist-section"]')),
      comments_header: inAside(aside.querySelector('hgroup')),
      comment_composer: inAside(q('[data-testid="card-back-comment-composer"]')),
      comments_list: inAside(q('[data-testid="card-back-actions-list"]')),
      comment_items: actions,
      nav: {rect: R(q('nav.cb-nav [role="group"]')), visible: clip(R(q('nav.cb-nav [role="group"]')), VP)},
      activity_button: R(btn),
      automation_toggle: R(autoToggle()),
      automation_popover: R(autoPopover()),
      automation_items: [...document.querySelectorAll('.atlaskit-portal section[role="dialog"] ul > li > button')].map(R),
      auto_bar: R(q('[data-twc-auto-bar]')),
      auto_buttons: [...document.querySelectorAll('[data-twc-auto-bar] .twc-auto-btn')].map(R),
    }, auto: auto()};
})()"""

BOARD_MEASURE_JS = "(() => {" + JS_HELPERS + r"""
  return {twc: twc(), counts: counts(), rects: {
    viewport: VP,
    board_header: R(document.querySelector('[data-testid="board-header"]')),
    board_name: R(document.querySelector('[data-testid="board-name-display"]')),
    lists: [...document.querySelectorAll('div[data-testid="list"]')].map(l => ({
      name: l.querySelector('[data-testid="list-name"]').textContent.trim(), rect: R(l)})),
    cards: boardCards()}};
})()"""

POPUP_MEASURE_JS = r"""(() => {
  const R = (e) => { const r = e.getBoundingClientRect();
    return {x: +r.x.toFixed(2), y: +r.y.toFixed(2), width: +r.width.toFixed(2), height: +r.height.toFixed(2)}; };
  const f = (id) => document.getElementById(id).closest('.field');
  return {body: R(document.body), head: R(document.querySelector('.head')),
          cardWidth_field: R(f('cardWidth')), descRatio_field: R(f('descRatio')),
          autoButtons_field: R(f('autoButtons')),
          colorField: R(document.getElementById('colorField')), foot: R(document.querySelector('.foot')),
          swatch: R(document.getElementById('swatch'))};
})()"""

POPUP_UI_JS = r"""(() => ({
  enabled: document.getElementById('enabled').checked,
  cardWidth: +document.getElementById('cardWidth').value,
  descRatio: +document.getElementById('descRatio').value,
  autoButtons: document.getElementById('autoButtons').checked,
  colorCards: document.getElementById('colorCards').checked,
  colorStrength: +document.getElementById('colorStrength').value,
  texts: {enabled: document.getElementById('enabledText').textContent, cardWidth: document.getElementById('cardWidthValue').textContent,
          ratio: document.getElementById('ratioValue').textContent, autoButtons: document.getElementById('autoButtonsText').textContent,
          colorCards: document.getElementById('colorCardsText').textContent,
          colorStrength: document.getElementById('colorStrengthValue').textContent},
  bodyOff: document.body.classList.contains('is-off'),
  colorsOff: document.getElementById('colorField').classList.contains('is-colors-off'),
  savedShown: document.getElementById('saved').classList.contains('show'),
}))()"""

STORAGE_JS = "new Promise(r => chrome.storage.sync.get(null, r))"


# ---------------------------------------------------------------------------
# 期待値（調査 §3.2 / §6 の実測と content.css の計算式）
# ---------------------------------------------------------------------------
def expected_widths(settings: dict, view: tuple, comments: str) -> dict:
    vw = view[0]
    open_ = comments == "open"
    if not settings["enabled"]:
        if open_:
            return {"dialog": 1080.0, "main": 620.0, "aside": 460.0}
        return {"dialog": 584.0, "main": 584.0}
    w = settings["cardWidth"]
    dialog = min(vw * w / 100.0, vw - (8 if w >= 100 else 24))
    if not open_:
        return {"dialog": dialog, "main": dialog}
    aside = dialog * (100 - settings["descRatio"]) / 100.0
    return {"dialog": dialog, "main": dialog - aside, "aside": aside}


def compare(measured: dict, expected: dict, tol: float = 0.6) -> dict:
    out = {}
    for k, v in expected.items():
        m = measured.get(k)
        out[k] = {"expected": round(v, 2), "measured": m,
                  "ok": m is not None and abs(m - v) <= tol}
    return out


# ---------------------------------------------------------------------------
# ページ操作
# ---------------------------------------------------------------------------
def settle(s: cdp.Session, extra: float = 0.4):
    s.evaluate("document.fonts.ready.then(() => document.fonts.status)", timeout=15)
    # 2 フレーム待って、レイアウトと描画が落ち着いてから撮る
    s.send("Page.bringToFront")
    s.evaluate("new Promise(r => { requestAnimationFrame(() => requestAnimationFrame(() => r(true))); "
               "setTimeout(() => r(false), 1500); })", timeout=15)
    time.sleep(extra)


def set_view(s: cdp.Session, view: tuple, dpr: float = DPR):
    s.send("Emulation.setDeviceMetricsOverride",
           {"width": view[0], "height": view[1], "deviceScaleFactor": dpr, "mobile": False})


def prepare_tab(s: cdp.Session):
    s.send("Emulation.setScrollbarsHidden", {"hidden": True})
    s.send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "light"}]})


def element_center(s: cdp.Session, js_element: str):
    r = s.evaluate(f"(() => {{ const e = {js_element}; if (!e) return null; const r = e.getBoundingClientRect(); "
                   "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    if not r:
        raise RuntimeError("element not found: " + js_element)
    return r


def user_click(s: cdp.Session, js_element: str):
    """要素の中心を本物のマウス操作でクリックし、マウスを画面の外へ逃がす（ホバー表示を残さない）。"""
    s.send("Page.bringToFront")
    x, y = element_center(s, js_element)
    s.click(x, y)
    s.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": 1, "y": 1, "button": "none"})


def screenshot(s: cdp.Session, path: str, clip: dict | None = None):
    s.send("Page.bringToFront")
    s.screenshot(path, clip=clip)
    with Image.open(path) as im:
        return list(im.size)


# ---------------------------------------------------------------------------
# ポップアップ（本物）で設定する
# ---------------------------------------------------------------------------
def popup_ui(p: cdp.Session) -> dict:
    return p.evaluate(POPUP_UI_JS)


def popup_set_range(p: cdp.Session, el_id: str, value: int):
    """スライダーに値を入れ、ドラッグしたときと同じく input（と離したときの change）を発火させる。"""
    p.send("Page.bringToFront")
    p.evaluate(f"""(() => {{ const e = document.getElementById({json.dumps(el_id)});
      e.focus(); e.value = {json.dumps(str(value))};
      e.dispatchEvent(new Event('input', {{bubbles: true}}));
      e.dispatchEvent(new Event('change', {{bubbles: true}})); e.blur(); return true; }})()""")


def apply_settings(p: cdp.Session, target: dict, actions: list):
    """ポップアップを利用者と同じ手順で操作して target の設定にする。"""
    ui = popup_ui(p)
    keys = ["cardWidth", "descRatio", "colorStrength"]
    need_inner = (any(ui[k] != target[k] for k in keys) or ui["colorCards"] != target["colorCards"]
                  or ui["autoButtons"] != target["autoButtons"])
    # 全体スイッチが OFF の間は項目が操作できないので、先に ON にする
    if (target["enabled"] or need_inner) and not ui["enabled"]:
        user_click(p, "document.querySelector('#enabled + .track')")
        actions.append("click: メインスイッチ → ON")
        ui = popup_ui(p)
    # 色付けが OFF の間は濃さのスライダーが操作できないので、先に ON にする
    if (target["colorCards"] or ui["colorStrength"] != target["colorStrength"]) and not ui["colorCards"]:
        user_click(p, "document.querySelector('#colorCards + .track')")
        actions.append("click: カードの色付け → ON")
    for k in keys:
        if ui[k] != target[k]:
            popup_set_range(p, k, target[k])
            actions.append(f"range: {k} = {target[k]}（input を発火）")
    ui = popup_ui(p)
    if ui["autoButtons"] != target["autoButtons"]:
        user_click(p, "document.querySelector('#autoButtons + .track')")
        actions.append(f"click: 自動化ボタンを常に表示 → {'ON' if target['autoButtons'] else 'OFF'}")
        ui = popup_ui(p)
    if not target["colorCards"] and ui["colorCards"]:
        user_click(p, "document.querySelector('#colorCards + .track')")
        actions.append("click: カードの色付け → OFF")
    if not target["enabled"] and ui["enabled"]:
        user_click(p, "document.querySelector('#enabled + .track')")
        actions.append("click: メインスイッチ → OFF")
    # 保存されたことを chrome.storage.sync で確かめる
    want = json.dumps(target, sort_keys=True, separators=(",", ":"))
    p.wait_for(f"""{STORAGE_JS}.then(st => JSON.stringify(Object.fromEntries(Object.keys(st).sort()
        .filter(k => {json.dumps(list(DEFAULTS))}.includes(k)).map(k => [k, st[k]]))) === {json.dumps(want)})""",
               timeout=10)


def popup_wait_clean(p: cdp.Session):
    """「保存しました」の表示（1.2 秒で消える）が消えるまで待つ。"""
    p.wait_for("!document.getElementById('saved').classList.contains('show') && "
               "getComputedStyle(document.getElementById('saved')).opacity === '0'", timeout=6)


# ---------------------------------------------------------------------------
# 再現ページの状態を待つ
# ---------------------------------------------------------------------------
def wait_page_state(s: cdp.Session, settings: dict, comments: str | None, timeout: float = 15.0,
                    page: str | None = None):
    on = settings["enabled"]
    color_on = settings["enabled"] and settings["colorCards"]
    auto_on = settings["enabled"] and settings["autoButtons"]
    conds = [
        f"st.twc.on === {json.dumps(on)}",
        f"st.twc.color === {json.dumps(settings['colorCards'])}",
        f"st.twc.vars['--twc-card-width'] === '{settings['cardWidth']}vw'",
        f"st.twc.vars['--twc-desc-ratio'] === '{settings['descRatio']}%'",
        f"st.twc.vars['--twc-color-strength'] === '{settings['colorStrength']}%'",
        "st.counts.labeled_cards > 0",
        ("st.counts.painted_cards === st.counts.labeled_cards" if color_on else "st.counts.painted_cards === 0"),
        "st.fonts === 'loaded'",
    ]
    if comments:
        conds.append(f"st.comments === '{'true' if comments == 'open' else 'false'}'")
    if page == "card":
        # 自動化ボタン: 拡張が「自動化」の一覧を見えない状態で開いて読み、閉じ終わって、列が並んだところで撮る
        conds += ["!st.auto.busy", "st.auto.pressed === 'false'", "st.auto.popover_items === 0"]
        conds.append(f"st.auto.buttons.length === {AUTO_BUTTONS}" if auto_on else "!st.auto.bar")
    expr = f"(() => {{ const st = {STATE_JS}; return ({' && '.join(conds)}) ? st : null; }})()"
    try:
        return s.wait_for(expr, timeout=timeout)
    except TimeoutError:
        raise RuntimeError("再現ページが期待した状態になりません: " + json.dumps(s.evaluate(STATE_JS), ensure_ascii=False))


AUTO_TOGGLE = "document.querySelector('nav.cb-nav button[aria-label=\"自動化\"]')"


def set_automation(s: cdp.Session, want: str, actions: list):
    """下部のナビの「自動化」を本物のクリックで開閉し、一覧が見えている（閉じた）状態になるまで待つ。"""
    open_ = want == "open"
    cur = s.evaluate(f"{AUTO_TOGGLE}.getAttribute('aria-pressed')")
    if (cur == "true") != open_:
        user_click(s, AUTO_TOGGLE)
        actions.append(f"click: 再現ページの下部ナビ「自動化」→ {'開く' if open_ else '閉じる'}")
    if open_:
        s.wait_for(f"(() => {{ const p = document.querySelector('.atlaskit-portal section[role=\"dialog\"]');"
                   f" return {AUTO_TOGGLE}.getAttribute('aria-pressed') === 'true' && !!p &&"
                   f" p.querySelectorAll('ul > li > button').length === {AUTO_BUTTONS} &&"
                   f" getComputedStyle(p).opacity === '1'; }})()", timeout=5)
    else:
        s.wait_for(f"{AUTO_TOGGLE}.getAttribute('aria-pressed') === 'false' && "
                   "!document.querySelector('.atlaskit-portal section[role=\"dialog\"]')", timeout=5)


def set_comments(s: cdp.Session, want: str, actions: list):
    cur = s.evaluate("document.querySelector('[data-testid=\"card-back-activity-button\"]').getAttribute('aria-checked')")
    target = "true" if want == "open" else "false"
    if cur != target:
        user_click(s, "document.querySelector('[data-testid=\"card-back-activity-button\"]')")
        actions.append(f"click: 再現ページの下部ナビ「コメント」→ {'開く' if want == 'open' else '閉じる'}")
        s.wait_for(f"document.querySelector('[data-testid=\"card-back-activity-button\"]').getAttribute('aria-checked') === '{target}'",
                   timeout=5)


# ---------------------------------------------------------------------------
def open_mock(b: cdp.Browser, ic: cdp.RequestInterceptor, url: str, view: tuple, label: str) -> cdp.Session:
    def before(s):
        ic.attach(s)
        prepare_tab(s)
    m = b.cdp.mark()
    s = b.new_page(width=view[0], height=view[1], dpr=DPR, before_navigate=before)
    s.navigate(url)
    s.wait_for("document.querySelector('a[data-testid=\"card-name\"]') !== null", timeout=15)
    ctxs = [ev["params"]["context"] for ev in s.events_since(m, "Runtime.executionContextCreated")]
    worlds = [{"name": c.get("name"), "origin": c.get("origin"), "type": c.get("auxData", {}).get("type")}
              for c in ctxs]
    log.setdefault("tabs", {})[label] = {"url": url, "execution_contexts": worlds}
    return s


def control_run(b: cdp.Browser, ic: cdp.RequestInterceptor) -> dict:
    """拡張を読み込む前に再現ページを開き、Trello 標準の状態を記録する（対照）。"""
    out = {}
    s = open_mock(b, ic, CARD_URL, (1440, 900), "control_card")
    settle(s, 0.2)
    m = s.evaluate(CARD_MEASURE_JS)
    out["card_1440_open"] = {
        "html_has_data_twc_on": m["twc"]["on"], "html_twc_vars": m["twc"]["vars"],
        "painted_cards": m["counts"]["painted_cards"], "labeled_cards": m["counts"]["labeled_cards"],
        "widths": m["widths"],
        "check": compare(m["widths"], expected_widths(S(enabled=False), (1440, 900), "open")),
        "execution_contexts": log["tabs"]["control_card"]["execution_contexts"]}
    set_comments(s, "closed", [])
    settle(s, 0.1)
    m = s.evaluate(CARD_MEASURE_JS)
    out["card_1440_closed"] = {"widths": m["widths"],
                               "check": compare(m["widths"], expected_widths(S(enabled=False), (1440, 900), "closed"))}
    b.close_page(s)
    return out


def scan_mock_sources() -> dict:
    """再現ページのファイルに、トレひろの印の名前（twc）が出てこないことを確かめる。"""
    hits = []
    for root, _, files in os.walk(MOCK_DIR):
        for fn in files:
            if not fn.endswith((".html", ".css", ".js")):
                continue
            path = os.path.join(root, fn)
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    if re.search(r"twc", line, re.I):
                        hits.append(f"{os.path.relpath(path, REPO)}:{i}")
    return {"pattern": "twc", "hits": hits, "ok": not hits}


# ---------------------------------------------------------------------------
def capture(args):
    os.makedirs(args.out, exist_ok=True)
    only = None
    if args.only:
        only = {n.strip().replace(".png", "") for n in args.only.split(",") if n.strip()}
        unknown = only - {s["name"] for s in SHOTS}
        if unknown:
            raise SystemExit(f"--only に知らない名前があります: {sorted(unknown)}（使える名前: "
                             f"{', '.join(s['name'] for s in SHOTS)}）")

    tmp_root = args.profile_dir or tempfile.mkdtemp(prefix="trehiro-capture-")
    udd = os.path.join(tmp_root, "chrome-profile")
    shutil.rmtree(udd, ignore_errors=True)
    log.update(started=dt.datetime.now().isoformat(timespec="seconds"),
               tool="store-assets/tools/capture_raw.py", dpr=DPR,
               mock={"dir": "store-assets/tools/mock", "board_url": BOARD_URL, "card_url": CARD_URL})

    b = cdp.Browser(args.browser, udd, ["--enable-unsafe-extension-debugging"], headless=not args.headed,
                    pipe=True, offline=True)
    ic = cdp.RequestInterceptor(b.cdp, cdp.MockSite(MOCK_DIR))
    try:
        # 一時プロファイルの場所は記録しない（実行した PC のパスを残さない）
        # 実行ファイルの場所も、ホームフォルダの下ならユーザー名を伏せる
        log["browser"] = {"executable": redact_home(b.exe), "version": b.version,
                          "argv": [redact_home(a.replace(udd, "<一時プロファイル>")) for a in b.argv[1:]]}
        try:
            # ブラウザ全体のリクエストも横取りの対象にする（Chrome 自身の通信も外へ出さず記録する）
            b.send("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
            log["browser"]["browser_level_fetch"] = True
        except cdp.CDPError as e:
            log["browser"]["browser_level_fetch"] = f"unavailable: {e}"

        # ---- 対照: 拡張なし ------------------------------------------------------
        print("[control] 拡張を読み込む前の再現ページ")
        log["verification"] = {"mock_sources_free_of_extension_marks": scan_mock_sources(),
                               "control_without_extension": control_run(b, ic)}

        # ---- 本物の拡張を読み込む ------------------------------------------------
        ext_id = b.send("Extensions.loadUnpacked", {"path": REPO})["id"]
        note(f"Extensions.loadUnpacked OK: id={ext_id}")
        popup_url = f"chrome-extension://{ext_id}/popup.html"

        def popup_before(s):
            ic.attach(s)
            prepare_tab(s)
        p = b.new_page(width=POPUP_VIEW[0], height=POPUP_VIEW[1], dpr=DPR, before_navigate=popup_before)
        p.navigate(popup_url)
        p.wait_for("document.getElementById('cardWidthValue').textContent.endsWith('%')")
        mf = p.evaluate("chrome.runtime.getManifest()")
        log["extension"] = {
            "id": ext_id, "path": "（リポジトリのルートを Extensions.loadUnpacked で読み込み）", "popup_url": popup_url,
            "manifest_as_loaded": {k: mf.get(k) for k in ("name", "version", "manifest_version", "description")},
            "action_default_title": (mf.get("action") or {}).get("default_title"),
            "content_scripts": [{"matches": c.get("matches"), "js": c.get("js"), "css": c.get("css"),
                                 "run_at": c.get("run_at")} for c in mf.get("content_scripts", [])],
            "permissions": mf.get("permissions"), "host_permissions": mf.get("host_permissions")}
        # 「既定値に戻す」を押して、既定値を明示的に保存した状態から始める
        user_click(p, "document.getElementById('reset')")
        p.wait_for(f"{STORAGE_JS}.then(st => st.enabled === true && st.cardWidth === 95)", timeout=10)
        popup_wait_clean(p)

        tabs = {}
        current = {"card": None}

        def tab(kind: str, view: tuple) -> cdp.Session:
            if kind not in tabs:
                url = CARD_URL if kind == "card" else BOARD_URL
                tabs[kind] = open_mock(b, ic, url, view, kind)
                ctx = log["tabs"][kind]["execution_contexts"]
                log["tabs"][kind]["content_script_world"] = [
                    c for c in ctx if c["type"] == "isolated" and (c["origin"] or "").endswith(ext_id)]
            s = tabs[kind]
            s.send("Page.bringToFront")
            set_view(s, view)
            return s

        stored_before = None
        for shot in SHOTS:
            if only and shot["name"] not in only:
                continue
            name = shot["name"]
            print(f"[{name}] {shot['desc']}")
            actions: list = []
            apply_settings(p, shot["settings"], actions)
            stored = p.evaluate(STORAGE_JS)
            ui = popup_ui(p)
            path = os.path.join(args.out, name + ".png")
            entry = {"file": name + ".png", "page": shot["page"], "description": shot["desc"],
                     "settings_target": shot["settings"], "settings_stored": stored,
                     "popup_ui": {k: ui[k] for k in ("texts", "bodyOff", "colorsOff")}, "actions": actions}

            if shot["page"] == "popup":
                popup_wait_clean(p)
                settle(p, 0.2)
                rects = p.evaluate(POPUP_MEASURE_JS)
                body = rects["body"]
                size = screenshot(p, path, clip={"x": body["x"], "y": body["y"], "width": body["width"],
                                                 "height": body["height"]})
                entry.update(size=size, viewport=list(POPUP_VIEW), dpr=DPR,
                             clip_css_px=body, rects=rects,
                             note="rects はビューポートの CSS px。画像は body を切り出したもの（原点 = body の左上）")
            else:
                view = shot["view"]
                s = tab(shot["page"], view)
                if shot["page"] == "card":
                    set_comments(s, shot["comments"], actions)
                st = wait_page_state(s, shot["settings"], shot.get("comments"), page=shot["page"])
                if shot.get("automation") == "open":
                    set_automation(s, "open", actions)
                settle(s)
                if shot["page"] == "card":
                    m = s.evaluate(CARD_MEASURE_JS)
                    exp = expected_widths(shot["settings"], view, shot["comments"])
                    entry.update(comments=shot["comments"], measured=m["widths"], computed=m["computed"],
                                 table_row_heights=m["table_rows"],
                                 check_vs_expected=compare(m["widths"], exp), rects=m["rects"])
                else:
                    m = s.evaluate(BOARD_MEASURE_JS)
                    entry.update(rects=m["rects"])
                entry.update(html_state=st["twc"], counts=m["counts"])
                if shot["page"] == "card":
                    entry.update(auto=m["auto"])
                size = screenshot(s, path)
                entry.update(size=size, viewport=list(view), dpr=DPR)
                if shot.get("automation") == "open":
                    # 次の素材に一覧が写り込まないよう、撮ったら閉じる
                    set_automation(s, "closed", actions)
                bad = [k for k, v in entry.get("check_vs_expected", {}).items() if not v["ok"]]
                if bad:
                    note(f"{name}: 期待値と違う幅があります: {bad}")
            print(f"  saved {name}.png {entry['size'][0]}x{entry['size'][1]}")
            log["shots"].append(entry)
            stored_before = stored

        log["final_settings_stored"] = stored_before
        # ページで起きた JS のエラー（再現ページ・ポップアップ）
        errs = [ev["params"].get("exceptionDetails", {}).get("text") for ev in b.cdp.events
                if ev.get("method") == "Runtime.exceptionThrown"]
        log["page_exceptions"] = errs
    finally:
        log["network"] = ic.summary()
        ic.stop()
        b.close()
        left = cdp.kill_leftovers(udd)
        if left:
            note(f"残っていたブラウザのプロセスを {left} 個終了しました")
        if not args.profile_dir:
            shutil.rmtree(tmp_root, ignore_errors=True)
        log["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        write_manifest(args.out, only)
    print("done ->", args.out)


def summarize(shots: list) -> list:
    """撮った素材ごとの要点（幅・比率・塗られた枚数）を 1 行ずつにまとめる。"""
    out = []
    for s in shots:
        row = {"file": s["file"], "page": s["page"], "viewport": s.get("viewport"),
               "settings": {k: s["settings_stored"].get(k) for k in DEFAULTS} if s.get("settings_stored") else None}
        if s["page"] == "card":
            m = s["measured"]
            row.update(comments=s["comments"], dialog=m["dialog"], main=m["main"],
                       aside=m["aside_visible"], ratio=m["ratio"], table=m["table"],
                       matches_expected=all(v["ok"] for v in s["check_vs_expected"].values()))
        if s["page"] in ("card", "board"):
            row.update(labeled_cards=s["counts"]["labeled_cards"], painted_cards=s["counts"]["painted_cards"],
                       html_data_twc_on=s["html_state"]["on"])
        if s["page"] == "card" and s.get("auto"):
            row.update(auto_bar_buttons=len(s["auto"]["buttons"]),
                       automation_popover_items=s["auto"]["popover_items"])
        out.append(row)
    return out


def write_manifest(out_dir: str, only):
    path = os.path.join(out_dir, "manifest.json")
    log["summary"] = summarize(log["shots"])
    data = log
    if only and os.path.exists(path):
        # 一部だけ撮り直したときは、前回の manifest に撮り直した分を差し替える
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        new_files = {s["file"] for s in log["shots"]}
        order = [s["name"] + ".png" for s in SHOTS]
        merged = [s for s in old.get("shots", []) if s["file"] not in new_files] + log["shots"]
        merged.sort(key=lambda s: order.index(s["file"]) if s["file"] in order else 999)
        data = dict(old)
        data.update({k: v for k, v in log.items() if k != "shots"})
        data["shots"] = merged
        data["summary"] = summarize(merged)
        data["partial_update"] = sorted(new_files)
    # 改行は OS によらず LF（リポジトリの .gitattributes と同じ。Windows でも作業コピーと差分が出ないように）
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--browser", default=None,
                    help="Chrome の実行ファイル（省略時は自動判定。環境変数 CHROME_PATH でも指定できる）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="出力先（既定: store-assets/raw）")
    ap.add_argument("--headed", action="store_true", help="ブラウザの画面を表示して撮る")
    ap.add_argument("--only", default=None,
                    help="撮る素材の名前（カンマ区切り。例: card_default,popup_default）")
    ap.add_argument("--profile-dir", default=None, help="一時プロファイルの置き場所（省略時は一時フォルダ）")
    args = ap.parse_args()
    capture(args)


if __name__ == "__main__":
    main()
