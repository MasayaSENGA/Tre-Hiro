/*
 * トレひろ – ボードのカードをラベル色で塗る / content script
 *
 * やること:
 *   1. ボード上のカードフロント（/c/xxxx へのリンク）を集める
 *   2. カード 1 枚ぶんの箱を求め、その中のラベルチップの
 *      「実際に描画されている色」を getComputedStyle で読む
 *   3. カードの面を描いている要素に CSS 変数を付けるだけ（塗るのは content.css 側）
 *
 * 色名やクラス名を一切ハードコードしないのがポイント。
 * Trello がラベルのパレット名（green_subtle など）やクラスを変えても、
 * 「チップの背景色をそのまま借りる」ので追従できる。
 *
 * 注意している Trello 側の事情:
 *   ・カードフロントのリンク <a> は「カード全体」とは限らない。
 *     ラベルがリンクの外（同じカードの別要素）にぶら下がることがある。
 *   ・カードの白い面（背景色）はリンクそのものではなく、
 *     内側のラッパー要素が持っていることがある。透明な外側に塗っても
 *     不透明な子に覆われて何も見えない。
 *   このため「カードの箱（unit）」と「面を描いている要素（surface）」を
 *   分けて求め、ラベルは unit から探し、色は surface に塗る。
 */

(() => {
  /** 色を付けたカードに付ける印。値は色の並び（差分検出のキー）を兼ねる。 */
  const MARK = "data-twc-card-color";
  /** カバー画像付きなど、触らないと決めたカードの印。 */
  const SKIP = "data-twc-nocolor";
  /** 左端の帯に描き分けるラベル色の最大数。これ以上は帯が細すぎて読めない。 */
  const MAX_BAR = 4;
  /** カードの箱を探して何段まで親をたどるか。 */
  const MAX_CLIMB = 4;
  /** カードの面を探して何段まで子へ降りるか。 */
  const MAX_DESCEND = 6;
  /** カード 1 枚としてありえる高さの上限（px）。目印が無いときの保険。 */
  const MAX_CARD_HEIGHT = 400;
  /** 「面を覆っている子」と見なす大きさの比率。 */
  const FILL_RATIO = 0.85;

  /*
   * カード 1 枚ぶんの箱の目印。現行の Trello はこの入れ子:
   *   div[data-testid="list-card-container"]
   *     div[data-testid="list-card-wrapper"]
   *       div[data-testid="trello-card"]        ← カードの面（背景色）はここ
   *         div > div（ラベルの帯）
   *              a[data-testid="card-name"]     ← リンクはタイトル行だけ
   * リンク＝カードではないので、まず箱まで登ってからラベルを探す。
   */
  const TILE_SELECTOR = [
    '[data-testid="trello-card"]',
    '[data-testid$="card-wrapper"]',
    '[data-testid$="card-container"]',
  ].join(",");

  /*
   * ラベルチップの目印。上から順に試すのではなく全部まとめて拾う
   * （Trello 側のバージョン差でどれが当たるか分からないため）。
   * data-testid はビルドをまたいでも比較的安定しているが、
   * card-label / compact-card-label / xxx-card-label と揺れるので
   * 部分一致で拾って、色が読めなかったものは後段で捨てる。
   */
  const LABEL_SELECTOR = [
    '[data-testid*="label"]',
    "[data-color-name]",
    "[data-color]",
  ].join(",");

  /** カードフロント（<a>）ごとの探索結果。毎回 DOM を測り直さないためのキャッシュ。 */
  const resolved = new WeakMap();

  let observer = null;
  let timer = 0;

  /* ------------------------------------------------------------------
     カードフロントを集める
     ------------------------------------------------------------------ */

  /**
   * ボード上のカードは必ず /c/<shortlink>/... へのリンク。
   * ハッシュ化されたクラス名ではなく、この URL 構造だけを頼りにする。
   */
  function cardFronts() {
    const out = [];
    for (const a of document.querySelectorAll('a[href*="/c/"]')) {
      if (!a.pathname || !a.pathname.startsWith("/c/")) continue;
      // カード詳細（カードバック）の本文中のカードリンクは対象外。
      if (a.closest('[role="dialog"]')) continue;
      out.push(a);
    }
    return out;
  }

  /* ------------------------------------------------------------------
     カード 1 枚ぶんの箱と、その面を描いている要素を求める
     ------------------------------------------------------------------ */

  /** その要素がカード 1 枚だけを包んでいるか（リスト側のコンテナを弾く）。 */
  function holdsOneCard(el) {
    return el.querySelectorAll('a[href*="/c/"]').length <= 1;
  }

  /**
   * カードフロントのリンクから、同じカードを表す箱まで登る。
   * まず data-testid の目印を探し、無ければ大きさを頼りにたどる。
   */
  function unitOf(a) {
    // リンク自身は箱ではないので、親から探し始める。
    const parent = a.parentElement;
    const tile = parent && parent.closest(TILE_SELECTOR);
    if (tile && holdsOneCard(tile)) return tile;
    return climb(a);
  }

  /**
   * 目印が見つからない Trello 版むけの保険。
   * 「他のカードを含み始めたら」「カード 1 枚には大きすぎたら」打ち切る。
   * リンクがカードの一部（タイトル行だけ）のこともあるので、
   * リンクの大きさを基準にしてはいけない。
   */
  function climb(a) {
    let unit = a;
    const base = a.getBoundingClientRect();

    let el = a.parentElement;
    for (let depth = 0; el && depth < MAX_CLIMB; depth++, el = el.parentElement) {
      if (el === document.body || el === document.documentElement) break;
      if (!holdsOneCard(el)) break;

      const r = el.getBoundingClientRect();
      if (r.height > MAX_CARD_HEIGHT) break;
      if (base.width && r.width > base.width * 2) break;

      unit = el;
    }
    return unit;
  }

  /** el とほぼ同じ大きさの子要素（＝面を覆っている子）を返す。 */
  function fillingChild(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return null;
    for (const child of el.children) {
      const c = child.getBoundingClientRect();
      if (c.width >= r.width * FILL_RATIO && c.height >= r.height * FILL_RATIO) {
        return child;
      }
    }
    return null;
  }

  /**
   * 実際に「カードの面」を描いている要素まで降りる。
   * 外側が透明で内側が不透明だと、外側に塗っても子に覆われて見えないため。
   * 面が見つからない（全部透明な）ときは箱そのものを塗る。
   */
  function surfaceOf(unit) {
    let el = unit;
    for (let depth = 0; depth < MAX_DESCEND; depth++) {
      if (!isTransparent(getComputedStyle(el).backgroundColor)) return el;
      const next = fillingChild(el);
      if (!next) break;
      el = next;
    }
    return unit;
  }

  /** カードフロントに対する { unit, surface }。DOM が作り直されたら測り直す。 */
  function targetOf(a) {
    const cached = resolved.get(a);
    if (
      cached &&
      cached.unit.isConnected &&
      cached.surface.isConnected &&
      cached.unit.contains(a)
    ) {
      return cached;
    }
    const unit = unitOf(a);
    const target = { unit, surface: surfaceOf(unit) };
    // まだレイアウトされていない（大きさ 0 の）カードは測っても当てにならないので、
    // 結果を覚えずに次の走査でやり直す。
    const rect = a.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) resolved.set(a, target);
    return target;
  }

  /* ------------------------------------------------------------------
     ラベル色を読む
     ------------------------------------------------------------------ */

  /** rgba(0,0,0,0) や transparent を「色なし」と判定する。 */
  function isTransparent(value) {
    if (!value || value === "transparent" || value === "none") return true;
    const inner = /^rgba?\(([^)]+)\)$/.exec(value);
    if (!inner) return false;
    // "r, g, b, a" と "r g b / a" の両方の記法に対応する。
    const parts = inner[1].split(/[,/]/).map((s) => s.trim());
    return parts.length > 3 && Number(parts[3]) < 0.05;
  }

  /** チップから「実際に見えている色」を取り出す。色名は解釈せず文字列のまま返す。 */
  function visibleColor(el) {
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return null;
    for (const value of [cs.backgroundColor, cs.borderTopColor]) {
      if (!isTransparent(value)) return value;
    }
    return null;
  }

  /** カード内のラベル色を、重複を除いて出現順に返す。 */
  function labelColors(unit, surface) {
    const colors = [];
    for (const el of unit.querySelectorAll(LABEL_SELECTOR)) {
      // ラベルの入れ物（透明なはず）がカードの面そのものだった場合の保険。
      if (el === unit || el === surface) continue;
      const color = visibleColor(el);
      if (color && !colors.includes(color)) colors.push(color);
    }
    return colors;
  }

  /** 左端の縦帯。ラベルが複数なら等分して積む。 */
  function barGradient(colors) {
    const list = colors.slice(0, MAX_BAR);
    if (list.length === 1) return `linear-gradient(${list[0]}, ${list[0]})`;
    const step = 100 / list.length;
    const stops = list.map(
      (c, i) => `${c} ${(step * i).toFixed(2)}% ${(step * (i + 1)).toFixed(2)}%`
    );
    return `linear-gradient(to bottom, ${stops.join(", ")})`;
  }

  /* ------------------------------------------------------------------
     塗る / 戻す
     ------------------------------------------------------------------ */

  function paint(a) {
    const { unit, surface } = targetOf(a);
    if (surface.hasAttribute(SKIP)) return;

    const colors = labelColors(unit, surface);
    if (!colors.length) {
      clear(surface);
      return;
    }

    if (!surface.hasAttribute(MARK)) {
      // カバー画像付きのカードは Trello の見た目を壊すので触らない。
      // （カバー「色」は background-color なので、ここでは引っかからない）
      const bg = getComputedStyle(surface).backgroundImage;
      if (bg && bg.includes("url(")) {
        surface.setAttribute(SKIP, "");
        return;
      }
    }

    const key = colors.join("|");
    if (surface.getAttribute(MARK) === key) return; // 前回から変化なし

    surface.setAttribute(MARK, key);
    surface.style.setProperty("--twc-card-color", colors[0]);
    surface.style.setProperty("--twc-card-bar", barGradient(colors));
  }

  function clear(el) {
    if (!el.hasAttribute(MARK) && !el.hasAttribute(SKIP)) return;
    el.removeAttribute(MARK);
    el.removeAttribute(SKIP);
    el.style.removeProperty("--twc-card-color");
    el.style.removeProperty("--twc-card-bar");
  }

  function scan() {
    timer = 0;
    for (const a of cardFronts()) paint(a);
  }

  function schedule() {
    if (timer) return;
    timer = setTimeout(scan, 120);
  }

  /* ------------------------------------------------------------------
     監視の開始 / 停止
     ------------------------------------------------------------------ */

  function start() {
    if (observer) return;
    /*
     * 属性は監視しない。自分で付ける data 属性 / style で
     * 監視が再発火する（無限ループになる）のを避けるため。
     * ラベルの増減・カードの追加はどちらも childList で拾える。
     */
    observer = new MutationObserver(schedule);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
    });
    schedule();
  }

  function stop() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    clearTimeout(timer);
    timer = 0;
    for (const el of document.querySelectorAll(`[${MARK}],[${SKIP}]`)) {
      clear(el);
    }
  }

  function apply(settings) {
    const s = twcNormalize(settings);
    if (s.enabled && s.colorCards) start();
    else stop();
  }

  function whenReady(fn) {
    // content script は document_start で走るので、body ができるまで待つ。
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  whenReady(() => {
    chrome.storage.sync.get(TWC_DEFAULTS, (stored) => {
      apply(chrome.runtime.lastError ? TWC_DEFAULTS : stored);
    });
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "sync") return;
    if (!["enabled", "colorCards"].some((key) => key in changes)) return;
    whenReady(() => {
      chrome.storage.sync.get(TWC_DEFAULTS, (stored) => apply(stored));
    });
  });
})();
