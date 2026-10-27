/*
 * トレひろ – カードの自動化ボタンを常に表示する / content script
 *
 * Trello のカード詳細では、カードボタン（Butler の自動化ボタン）は
 * 下に浮いているナビの「自動化」を押して開くポップオーバーの中にしかなく、
 * 実行するのに毎回 2 クリックかかる。そこでカード詳細の一番下にボタンを並べ、
 * 1 クリックで実行できるようにする。
 *
 * 並べるのは「代理」のボタンで、自分では何も実行しない。押されたら
 * Trello の「自動化」ポップオーバーを見えない状態で開き、同じ名前のボタンを
 * 押して、終わったら閉じるだけ。実行・権限・成功／失敗の通知は Trello 自身に
 * 任せるので、Trello や Butler の API は一切たたかない。
 * ボタンの一覧も同じやり方で、カード詳細を開いたときにポップオーバーから読む。
 * ページから読むのは、ポップオーバーの中のボタンの名前とアイコン（の画像の URL）だけ。
 * ページの通信やカードの名前・説明・コメントは見ない。
 *
 * 想定している Trello 側の構造（2026 年 10 月時点）:
 *   div[role="dialog"][data-testid="card-back-name"]
 *     … > div（枠。flex の縦並びで、max-height はウィンドウの高さ − 128px）
 *           header
 *           div
 *           div（main と aside の横並び）
 *           ← ここ（枠の最後の子）にボタン列を足す
 *         nav（カード詳細の下に浮くナビ）> div[role="group"]
 *           button[aria-label="Power-Up"][aria-pressed]
 *           button[aria-label="自動化"][aria-pressed]      ← 開閉のトグル
 *           span[role="separator"]
 *           button[data-testid="card-back-activity-button"]
 *   .atlaskit-portal-container > .atlaskit-portal > … > section[role="dialog"]
 *     … ul > li > button（カードボタン。アイコンの div ＋ 名前）
 *       ul > button「ボタンを追加」（li に入っていない）
 *     実行中はアイコンが [data-testid="spinner-wrapper"] に変わり、
 *     終わるとポップオーバーの外に「成功！」のフラグが出る（ポップオーバーは開いたまま）。
 *
 * 注意している Trello 側の事情:
 *   ・トグルの aria-pressed は、クリックした直後ではなく次のマイクロタスクで変わる。
 *   ・ページを開いて最初にポップオーバーを開いたときは、「ul はあるがボタンが 0 件」の
 *     状態が 0.5 秒ほど続いてから一覧が届く（中身の JS とボタン一覧の通信を待っている）。
 *     この途中の状態は、ボタンが 1 つもないボードの見た目と区別がつかない。
 *   ・ポップオーバーは開くとフォーカスを奪い、閉じると元とは別の場所にフォーカスを返す。
 */

(() => {
  /** 足したボタン列に付ける印。 */
  const BAR = "data-twc-auto-bar";
  /** ポップオーバーを開いた直後、まだ要素を特定できていない間だけ <html> に付ける印。 */
  const BUSY = "data-twc-auto-busy";
  /** 見えない状態で操作しているポップオーバーに付ける印。 */
  const HIDDEN = "data-twc-auto-hidden";

  /** ナビの「自動化」ボタンの aria-label（Trello の表示言語ごと）。 */
  const TOGGLE_LABELS = ["自動化", "自动化", "Automation"];
  /**
   * 「自動化」ボタンの雷アイコンの path の書き出し。表示言語に左右されない目印。
   * Power-Up ボタンなどを取り違えて押さないよう、場所（何番目か）では探さない。
   */
  const BOLT_PATH = "M10.377.102";

  /** トグルを押してから、開いた状態になるまで待つ上限。 */
  const TOGGLE_TIMEOUT = 1000;
  /** ポップオーバーが開いて一覧の ul が出るまで待つ上限（初回は中身の JS の読み込みがある）。 */
  const OPEN_TIMEOUT = 8000;
  /**
   * ul が出てからボタン 0 件のまま、「0 件」とみなすまでの時間。
   * 初回は ul が出てから一覧が届くまで 0.3〜0.6 秒ほどかかった（実測）ので、余裕を持たせる。
   */
  const EMPTY_TIMEOUT = 1500;
  /**
   * 前にボタンが 0 件だったボードでの EMPTY_TIMEOUT。Trello が一覧を覚えているときは
   * ul と同時にボタンが描かれる（実測 60ms ほど）ので、長く待つ必要はない。
   */
  const EMPTY_TIMEOUT_KNOWN = 400;
  /** 一覧が出てから、書き換えが落ち着くまで待つ時間と上限。 */
  const SETTLE_QUIET = 150;
  const SETTLE_MAX = 1500;
  /** ボタンを押してから、実行中の表示が出るまで待つ上限。 */
  const START_TIMEOUT = 1500;
  /** 実行中の表示が消えるまで待つ上限。 */
  const RUN_TIMEOUT = 30000;
  /** 一覧の読み取りに失敗したとき、同じカードで試し直す回数と間隔。 */
  const MAX_ATTEMPTS = 3;
  const RETRY_DELAY = 2000;

  const CLOSED = "closed";

  let observer = null;
  let timer = 0;
  /** ポップオーバーを操作中か（同時に 2 つは操作しない）。 */
  let busy = false;
  /** 操作中にユーザーがどこかを押したか。押されたらポップオーバーは Trello が閉じる。 */
  let interrupted = false;
  /** 読み取った一覧。{ key, items: [{ name, icon }] } */
  let current = null;
  /** カードごとの読み取りの試行。 */
  let attempts = { key: null, count: 0, retryAt: 0 };
  /** 今の設定。 */
  let settings = twcNormalize(TWC_DEFAULTS);
  /**
   * カードの shortLink → そのカードのボードの shortLink（調べられなかったら ""）。
   * 調べている間は undefined を入れておき、同じカードで二重に問い合わせない。
   */
  const boardOfCard = new Map();
  /** 入力中なので読み取りを後回しにしているか。 */
  let deferred = false;
  /**
   * ボタンが 0 件だったボードの画面の要素（ページを開いている間だけ覚える）。
   * DOM にはボードの ID が無く、名前などの文字は読みたくないので、要素そのもので見分ける。
   * Trello が別のボードでも同じ要素を使い回していても、待ち時間が短くなるだけで、
   * Trello が一覧を覚えていればボタンは読める。
   */
  const emptyBoards = new WeakSet();

  /* ------------------------------------------------------------------
     Trello 側の要素を探す
     ------------------------------------------------------------------ */

  function cardDialog() {
    return (
      document.querySelector('div[role="dialog"][data-testid="card-back-name"]') ||
      document.querySelector('#layer-manager-card-back div[role="dialog"]')
    );
  }

  /** カード詳細の下に浮いているナビ（「コメント」ボタンがあるもの）。 */
  function navOf(dialog) {
    for (const nav of dialog.querySelectorAll("nav")) {
      if (nav.querySelector('[data-testid="card-back-activity-button"]')) return nav;
    }
    return null;
  }

  /** ナビの「自動化」ボタン。aria-label か雷アイコンで見分ける。 */
  function automationToggle(dialog) {
    const nav = navOf(dialog);
    if (!nav) return null;
    const toggles = [...nav.querySelectorAll("button[aria-pressed]")];
    return (
      toggles.find((b) => TOGGLE_LABELS.includes((b.getAttribute("aria-label") || "").trim())) ||
      toggles.find((b) => {
        const path = b.querySelector("svg path");
        return !!path && (path.getAttribute("d") || "").startsWith(BOLT_PATH);
      }) ||
      null
    );
  }

  function isUsable(toggle) {
    return (
      !!toggle &&
      toggle.isConnected &&
      !toggle.disabled &&
      toggle.getAttribute("aria-disabled") !== "true"
    );
  }

  function isOpen(toggle) {
    return toggle.getAttribute("aria-pressed") === "true";
  }

  /** ボタン列を足す枠（main と aside の横並びの親で、header を持つもの）。 */
  function frameOf(dialog) {
    const main = dialog.querySelector("main");
    const row = main && main.parentElement;
    const frame = row && row.parentElement;
    if (!frame || !dialog.contains(frame)) return null;
    if (![...frame.children].some((c) => c.tagName === "HEADER")) return null;
    return frame;
  }

  function portalPopovers() {
    return [...document.querySelectorAll('.atlaskit-portal section[role="dialog"]')];
  }

  /** ポータルに出ているポップオーバーのうち、一番新しいもの（except にあるものは除く）。 */
  function latestPopover(except) {
    const all = portalPopovers().filter((p) => !except || !except.has(p));
    return all.length ? all[all.length - 1] : null;
  }

  /** ユーザーが開いている「自動化」ポップオーバー（一覧の ul があるもの）。 */
  function openPopover() {
    const pop = latestPopover();
    return pop && pop.querySelector("ul") ? pop : null;
  }

  /** ポップオーバー内のカードボタン。「ボタンを追加」は li に入っていないので当たらない。 */
  function itemButtons(pop) {
    return [...pop.querySelectorAll("ul > li > button")].filter((b) => b.textContent.trim());
  }

  function itemsOf(pop) {
    return itemButtons(pop).map((b) => {
      const icon = b.querySelector('[style*="background-image"]');
      return {
        name: b.textContent.trim(),
        icon: icon ? icon.style.backgroundImage : "",
      };
    });
  }

  function isSpinning(button) {
    return (
      !!button.querySelector('[data-testid="spinner-wrapper"]') ||
      button.getAttribute("aria-busy") === "true"
    );
  }

  /** カードの後ろに出ているボードの画面の要素。 */
  function boardView() {
    return document.querySelector('[data-testid="board-view"]');
  }

  /** カードを区別するキー。URL の /c/<shortLink>/ を使う。 */
  function cardKey() {
    const m = /^\/c\/([^/]+)/.exec(location.pathname);
    return m ? m[1] : "";
  }

  /** Trello 自身の API でボードの shortLink と名前を調べる。失敗したら null。 */
  async function fetchBoard(path) {
    try {
      const res = await fetch(`${location.origin}${path}?fields=shortLink,name`, {
        credentials: "same-origin",
      });
      if (!res.ok) return null;
      const board = await res.json();
      return board && board.shortLink ? { id: board.shortLink, name: board.name || "" } : null;
    } catch {
      return null;
    }
  }

  /** 開いているボードを調べる。カード詳細なら、そのカードのボード。 */
  function currentBoard() {
    const m = /^\/([bc])\/([^/]+)/.exec(location.pathname);
    if (!m) return Promise.resolve(null);
    const id = encodeURIComponent(m[2]);
    return fetchBoard(m[1] === "b" ? `/1/boards/${id}` : `/1/cards/${id}/board`);
  }

  /** カードのボードの shortLink。調べ終わるまでは undefined を返し、終わったら読み直す。 */
  function boardOf(key) {
    if (boardOfCard.has(key)) return boardOfCard.get(key);
    boardOfCard.set(key, undefined);
    fetchBoard(`/1/cards/${encodeURIComponent(key)}/board`).then((board) => {
      boardOfCard.set(key, board ? board.id : "");
      schedule();
    });
    return undefined;
  }

  /** このカードで自動化ボタンを並べるか。「常に表示」が OFF なら、指定したボードだけ。 */
  function isTargetCard(key) {
    if (settings.autoButtons) return true;
    const board = boardOf(key);
    return !!board && settings.autoButtonsBoards.some((b) => b.id === board);
  }

  /** 入力欄・エディタに入力中か。ポップオーバーを開くとフォーカスを奪うので、その間は読まない。 */
  function isEditing() {
    const el = document.activeElement;
    if (!el || el === document.body) return false;
    if (el.isContentEditable) return true;
    return el.matches(
      'input:not([type="button"]):not([type="checkbox"]):not([type="radio"]), textarea, select'
    );
  }

  /* ------------------------------------------------------------------
     ポップオーバーを見えない状態で操作する
     ------------------------------------------------------------------ */

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /** test() が値を返すまで待つ。時間切れなら null。 */
  async function waitFor(test, timeout) {
    const end = Date.now() + timeout;
    for (;;) {
      const value = test();
      if (value) return value;
      if (Date.now() >= end) return null;
      await sleep(50);
    }
  }

  /** ポップオーバーの書き換えが SETTLE_QUIET のあいだ止まるまで待つ。 */
  function settle(pop) {
    return new Promise((resolve) => {
      let quiet = 0;
      let limit = 0;
      const mo = new MutationObserver(() => {
        clearTimeout(quiet);
        quiet = setTimeout(done, SETTLE_QUIET);
      });
      function done() {
        clearTimeout(quiet);
        clearTimeout(limit);
        mo.disconnect();
        resolve();
      }
      mo.observe(pop, { childList: true, subtree: true });
      quiet = setTimeout(done, SETTLE_QUIET);
      limit = setTimeout(done, SETTLE_MAX);
    });
  }

  function onPointerDown(event) {
    if (event.isTrusted) interrupted = true;
  }

  /**
   * 見えないポップオーバーは開くとフォーカスを奪う（中の「自動化を編集」などに入る）。
   * その間のキー操作で、見えないボタンが押されないように止める。
   */
  function onKey(event) {
    const target = event.target;
    if (target instanceof Element && target.closest(`[${HIDDEN}]`)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }

  const KEY_EVENTS = ["keydown", "keypress", "keyup"];

  /**
   * 一覧が出そろうのを待つ。ボタンが 1 つでも出たら、書き換えが落ち着いたところで終わり。
   * 0 件のまま emptyWait たったら 0 件とみなす。途中で閉じられたら CLOSED。
   */
  async function whenListed(pop, emptyWait) {
    const since = performance.now();
    const state = await waitFor(() => {
      if (interrupted || !pop.isConnected) return CLOSED;
      if (itemButtons(pop).length) return "items";
      return performance.now() - since > emptyWait ? "empty" : null;
    }, OPEN_TIMEOUT);
    if (state === "items") await settle(pop);
    return state || "empty";
  }

  /**
   * ポップオーバーを開いて fn(pop) を実行し、閉じる。
   * ユーザーが自分で開いているときは、それをそのまま使い、閉じない。
   * 開けなかった（途中で閉じられた・時間切れ）ときは null を返す。
   * emptyWait は、ボタン 0 件のまま待つ時間（whenListed）。
   */
  async function withPopover(toggle, fn, emptyWait = EMPTY_TIMEOUT) {
    const opened = isOpen(toggle) && openPopover();
    if (opened) return fn(opened);

    const root = document.documentElement;
    const previousFocus = document.activeElement;
    // 押す前から出ているポップオーバーは、これから開くものではない。
    const before = new Set(portalPopovers());
    let pop = null;

    busy = true;
    interrupted = false;
    window.addEventListener("pointerdown", onPointerDown, true);
    for (const type of KEY_EVENTS) window.addEventListener(type, onKey, true);
    root.setAttribute(BUSY, "");
    try {
      toggle.click();
      if (!(await waitFor(() => isOpen(toggle), TOGGLE_TIMEOUT))) return null;

      const found = await waitFor(() => {
        if (interrupted || !toggle.isConnected || !isOpen(toggle)) return CLOSED;
        const p = latestPopover(before);
        if (!p) return null;
        // 要素が分かったら、隠すのはその要素だけにする（ほかのポップオーバーを巻き込まない）。
        p.setAttribute(HIDDEN, "");
        root.removeAttribute(BUSY);
        return p.querySelector("ul") ? p : null;
      }, OPEN_TIMEOUT);
      if (!found || found === CLOSED) return null;
      pop = found;

      if ((await whenListed(pop, emptyWait)) === CLOSED) return null;
      return await fn(pop);
    } finally {
      window.removeEventListener("pointerdown", onPointerDown, true);
      for (const type of KEY_EVENTS) window.removeEventListener(type, onKey, true);
      // ユーザーが押した場合は Trello が閉じている最中なので、ここで押すと開き直してしまう。
      if (interrupted) await sleep(100);
      if (toggle.isConnected && isOpen(toggle)) toggle.click();
      const hidden = pop || document.querySelector(`[${HIDDEN}]`);
      if (hidden) {
        // 閉じ終わる前に印を外すと、閉じるアニメーションが一瞬見えてしまう。
        await waitFor(() => !hidden.isConnected, 1000);
        hidden.removeAttribute(HIDDEN);
      }
      root.removeAttribute(BUSY);
      // ポップオーバーはフォーカスを奪い、別の場所に返すので、元に戻す。
      // ユーザーがどこかを押したときは、そちらのフォーカスを優先する。
      if (
        !interrupted &&
        previousFocus &&
        previousFocus !== document.body &&
        previousFocus.isConnected &&
        typeof previousFocus.focus === "function"
      ) {
        previousFocus.focus({ preventScroll: true });
      }
      busy = false;
      schedule();
    }
  }

  /* ------------------------------------------------------------------
     一覧の読み取り
     ------------------------------------------------------------------ */

  function sameItems(a, b) {
    return (
      a.length === b.length &&
      a.every((item, i) => item.name === b[i].name && item.icon === b[i].icon)
    );
  }

  /** 開いたカードの一覧を読む。 */
  async function load(key, toggle) {
    if (attempts.key !== key) attempts = { key, count: 0, retryAt: 0 };
    attempts.count++;

    const board = boardView();
    const emptyWait = board && emptyBoards.has(board) ? EMPTY_TIMEOUT_KNOWN : EMPTY_TIMEOUT;
    const items = await withPopover(toggle, (pop) => itemsOf(pop), emptyWait);
    if (cardKey() !== key || !cardDialog()) return; // 読んでいる間に別のカードに移った
    if (items) {
      current = { key, items };
      if (board) {
        if (items.length) emptyBoards.delete(board);
        else emptyBoards.add(board);
      }
    } else if (attempts.count >= MAX_ATTEMPTS) {
      current = { key, items: [] }; // あきらめる（ボタン列は出さない）
    } else {
      attempts.retryAt = Date.now() + RETRY_DELAY;
      setTimeout(schedule, RETRY_DELAY);
    }
    schedule();
  }

  /* ------------------------------------------------------------------
     ボタン列の描画
     ------------------------------------------------------------------ */

  const SVG_NS = "http://www.w3.org/2000/svg";

  /** 見出しの雷アイコン（自作の簡単な図形）。 */
  function boltIcon() {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "14");
    svg.setAttribute("height", "14");
    svg.setAttribute("aria-hidden", "true");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", "M9.5 1 3 9.25h4.25L6.5 15 13 6.75H8.75z");
    path.setAttribute("fill", "currentColor");
    svg.appendChild(path);
    return svg;
  }

  function buildBar(items) {
    const bar = document.createElement("div");
    bar.setAttribute(BAR, "");
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-label", "自動化（カードボタン）");

    const head = document.createElement("span");
    head.className = "twc-auto-head";
    head.appendChild(boltIcon());
    head.appendChild(document.createTextNode("自動化"));
    bar.appendChild(head);

    items.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "twc-auto-btn";
      button.dataset.twcAutoIndex = String(index);
      button.title = `「${item.name}」を実行`;

      const icon = document.createElement("span");
      icon.className = "twc-auto-icon";
      icon.setAttribute("aria-hidden", "true");
      if (item.icon) icon.style.backgroundImage = item.icon;

      const name = document.createElement("span");
      name.className = "twc-auto-name";
      name.textContent = item.name;

      button.append(icon, name);
      bar.appendChild(button);
    });

    bar.addEventListener("click", onBarClick);
    bar.twcItems = items;
    return bar;
  }

  /** 枠の最後にボタン列を置く。一覧が空なら置かない。 */
  function render(frame, items) {
    const bars = document.querySelectorAll(`[${BAR}]`);
    const bar = bars.length === 1 ? bars[0] : null;

    if (!items.length) {
      removeBars();
      return;
    }
    if (bar && bar.twcItems && sameItems(bar.twcItems, items)) {
      // 中身は同じ。Trello が枠に子を足して最後でなくなったときだけ動かす。
      if (frame.lastElementChild !== bar) frame.appendChild(bar);
      return;
    }
    removeBars();
    frame.appendChild(buildBar(items));
  }

  function removeBars() {
    for (const bar of document.querySelectorAll(`[${BAR}]`)) bar.remove();
  }

  /* ------------------------------------------------------------------
     代理ボタンを押したとき
     ------------------------------------------------------------------ */

  function setRunning(bar, button, running) {
    // disabled にするとフォーカスが外れてしまうので、印で止める（押せないのは CSS と onBarClick）。
    bar.toggleAttribute("data-twc-auto-running", running);
    if (running) button.setAttribute("aria-busy", "true");
    else button.removeAttribute("aria-busy");
  }

  function onBarClick(event) {
    const bar = event.currentTarget;
    const button = event.target.closest(".twc-auto-btn");
    if (!button || busy || !current || bar.hasAttribute("data-twc-auto-running")) return;
    run(bar, button, Number(button.dataset.twcAutoIndex));
  }

  async function run(bar, button, index) {
    const item = current.items[index];
    if (!item) return;
    // 同じ名前のボタンが複数あるときは、何番目かで区別する。
    const nth = current.items.slice(0, index).filter((i) => i.name === item.name).length;
    const key = current.key;

    setRunning(bar, button, true);
    try {
      // ユーザーがポップオーバーを開いていた場合、このクリックで閉じる処理が先に走るのを待つ。
      await sleep(50);
      const dialog = cardDialog();
      const toggle = dialog && automationToggle(dialog);
      if (!isUsable(toggle)) return;

      const items = await withPopover(toggle, async (pop) => {
        const target = itemButtons(pop).filter((b) => b.textContent.trim() === item.name)[nth];
        if (target) {
          target.click();
          // 実行中の表示が出て、消えるまで待つ（閉じるのは実行が終わってから）。
          const started = await waitFor(
            () => !target.isConnected || isSpinning(target),
            START_TIMEOUT
          );
          if (started) {
            await waitFor(() => !target.isConnected || !isSpinning(target), RUN_TIMEOUT);
          }
        }
        // ついでに一覧を最新にする（ボタンが増減・改名されていた場合のため）。
        return itemsOf(pop);
      });
      if (items && current && current.key === key) current.items = items;
    } finally {
      if (bar.isConnected) setRunning(bar, button, false);
      schedule();
    }
  }

  /* ------------------------------------------------------------------
     走査
     ------------------------------------------------------------------ */

  function onFocusOut() {
    deferred = false;
    schedule();
  }

  function scan() {
    timer = 0;
    if (busy) return;

    const dialog = cardDialog();
    if (!dialog) {
      current = null;
      attempts = { key: null, count: 0, retryAt: 0 };
      removeBars();
      return;
    }
    const toggle = automationToggle(dialog);
    const frame = frameOf(dialog);
    if (!frame || !isUsable(toggle)) {
      // 権限がなくて「自動化」が押せない・構造が想定と違う、のどちらか。
      removeBars();
      return;
    }

    const key = cardKey();
    if (!isTargetCard(key)) {
      removeBars();
      return;
    }
    if (!current || current.key !== key) {
      removeBars();
      if (attempts.key === key && Date.now() < attempts.retryAt) return;
      if (isEditing()) {
        // 入力中にフォーカスを奪わないよう、入力欄から離れるまで待つ。
        if (!deferred) {
          deferred = true;
          document.addEventListener("focusout", onFocusOut, { once: true, capture: true });
        }
        return;
      }
      load(key, toggle);
      return;
    }

    // ユーザーが自分でポップオーバーを開いたら、その一覧に合わせておく。
    if (isOpen(toggle)) {
      const pop = openPopover();
      if (pop) {
        const items = itemsOf(pop);
        if (items.length && !sameItems(items, current.items)) current.items = items;
      }
    }
    render(frame, current.items);
  }

  function schedule() {
    if (!observer || timer) return;
    timer = setTimeout(scan, 150);
  }

  /* ------------------------------------------------------------------
     監視の開始 / 停止
     ------------------------------------------------------------------ */

  function start() {
    if (observer) return;
    // 属性は監視しない（自分で付ける印で再発火しないように）。
    // カード詳細の開閉・ポップオーバーの開閉はどちらも childList で拾える。
    observer = new MutationObserver(schedule);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    schedule();
  }

  function stop() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    clearTimeout(timer);
    timer = 0;
    current = null;
    attempts = { key: null, count: 0, retryAt: 0 };
    removeBars();
  }

  function apply(stored) {
    settings = twcNormalize(stored);
    if (settings.enabled && (settings.autoButtons || settings.autoButtonsBoards.length)) {
      start();
      schedule();
    } else {
      stop();
    }
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
    if (!["enabled", "autoButtons", "autoButtonsBoards"].some((key) => key in changes)) return;
    whenReady(() => {
      chrome.storage.sync.get(TWC_DEFAULTS, (stored) => apply(stored));
    });
  });

  // ポップアップの「開いているボードを追加」から、今のボードを聞かれる。
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.type !== "twc-current-board") return false;
    currentBoard().then((board) => sendResponse({ board }));
    return true;
  });
})();
