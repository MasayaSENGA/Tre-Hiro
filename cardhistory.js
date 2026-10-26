/*
 * トレひろ – カードの変更履歴（JSON）を開くボタン
 *
 * Trello 自身の API（/1/cards/{カードID}/actions）の URL を新しいタブで開くだけで、
 * 拡張からは通信しない。表示されるのはログイン中の Trello が返す JSON そのもの。
 */

(() => {
  "use strict";

  const BUTTON = "data-twc-card-history";
  const COPY_BUTTON = "data-twc-copy-card-url";
  let enabled = false;
  let observer = null;

  function cardDialog() {
    return (
      document.querySelector('div[role="dialog"][data-testid="card-back-name"]') ||
      document.querySelector("#layer-manager-card-back div[role=\"dialog\"]")
    );
  }

  // 既定では最新 50 件しか返らないため、API の上限（1000 件）まで取得する。
  function historyUrl() {
    const match = /^\/c\/([^/]+)(?:\/|$)/.exec(location.pathname);
    if (!match) return "";
    return `${location.origin}/1/cards/${match[1]}/actions?filter=updateCard&limit=1000`;
  }

  function makeIcon() {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "16");
    svg.setAttribute("height", "16");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.5");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = '<path d="M2.25 8A5.75 5.75 0 1 0 8 2.25a6.2 6.2 0 0 0-4.3 1.75L2.25 5.5"/><path d="M2.25 2.5v3h3"/><path d="M8 5v3l2.25 1.25"/>';
    return svg;
  }

  function addButton(dialog) {
    const header = dialog.querySelector("header");
    const actions = header && header.querySelector("ul");
    if (!actions || actions.querySelector(`[${BUTTON}]`)) return;

    const item = document.createElement("li");
    item.setAttribute(BUTTON, "");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "twc-card-history";
    button.setAttribute("aria-label", "カードの変更履歴（JSON）を新しいタブで開く");
    button.title = "カードの変更履歴（JSON）を新しいタブで開く";
    button.appendChild(makeIcon());
    button.addEventListener("click", () => {
      const url = historyUrl();
      if (url) window.open(url, "_blank", "noopener");
    });
    item.appendChild(button);

    // ヘッダー右上の操作列で、カードURLのコピー（cardurl.js が先頭に置く）のすぐ後ろに置く。
    // どちらが先に置かれても、並びは「コピー → 履歴」になる。
    const copyItem = actions.querySelector(`:scope > [${COPY_BUTTON}]`);
    actions.insertBefore(item, copyItem ? copyItem.nextElementSibling : actions.firstElementChild);
  }

  function scan() {
    const dialog = cardDialog();
    if (enabled && dialog) addButton(dialog);
    else document.querySelectorAll(`[${BUTTON}]`).forEach((item) => item.remove());
  }

  function start() {
    if (observer) return;
    observer = new MutationObserver(scan);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    scan();
  }

  function apply(settings) {
    const s = twcNormalize(settings);
    enabled = s.enabled && s.cardHistory;
    if (enabled) start();
    else {
      if (observer) observer.disconnect();
      observer = null;
      document.querySelectorAll(`[${BUTTON}]`).forEach((item) => item.remove());
    }
  }

  function whenReady(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else fn();
  }

  whenReady(() => {
    chrome.storage.sync.get(TWC_DEFAULTS, (stored) => {
      apply(chrome.runtime.lastError ? TWC_DEFAULTS : stored);
    });
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "sync") return;
    if (!["enabled", "cardHistory"].some((key) => key in changes)) return;
    whenReady(() => {
      chrome.storage.sync.get(TWC_DEFAULTS, (stored) => apply(stored));
    });
  });
})();
