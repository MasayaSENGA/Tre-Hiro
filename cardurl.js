/*
 * トレひろ – カードURLをコピーするボタン
 */

(() => {
  "use strict";

  const BUTTON = "data-twc-copy-card-url";
  let enabled = true;
  let observer = null;
  let timer = 0;

  function cardDialog() {
    return (
      document.querySelector('div[role="dialog"][data-testid="card-back-name"]') ||
      document.querySelector("#layer-manager-card-back div[role=\"dialog\"]")
    );
  }

  function cardUrl() {
    const match = /^\/c\/([^/]+)(?:\/|$)/.exec(location.pathname);
    if (!match) return "";
    return `${location.origin}/c/${match[1]}/`;
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
    svg.innerHTML = '<rect x="5.25" y="2.25" width="8.5" height="10.5" rx="1.5"/><path d="M10.75 12.75v1A1.25 1.25 0 0 1 9.5 15h-6A1.25 1.25 0 0 1 2.25 13.75v-8.5A1.25 1.25 0 0 1 3.5 4h1.75"/>';
    return svg;
  }

  function showResult(button, copied) {
    button.setAttribute("aria-label", copied ? "カードURLをコピーしました" : "カードURLをコピーできませんでした");
    button.dataset.copied = copied ? "true" : "false";
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (!button.isConnected) return;
      button.setAttribute("aria-label", "カードURLをコピー");
      delete button.dataset.copied;
    }, 1800);
  }

  function addButton(dialog) {
    const header = dialog.querySelector("header");
    const actions = header && header.querySelector("ul");
    if (!actions || actions.querySelector(`[${BUTTON}]`)) return;

    const item = document.createElement("li");
    item.setAttribute(BUTTON, "");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "twc-copy-card-url";
    button.setAttribute("aria-label", "カードURLをコピー");
    button.title = "カードURLをコピー";
    button.appendChild(makeIcon());
    button.addEventListener("click", async () => {
      const url = cardUrl();
      const copied = !!url && await twcCopyText(url);
      showResult(button, copied);
    });
    item.appendChild(button);

    // ヘッダー右上の操作列の先頭に置く。
    actions.insertBefore(item, actions.firstElementChild);
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
    enabled = !!settings.enabled;
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
    if (areaName !== "sync" || !("enabled" in changes)) return;
    whenReady(() => {
      chrome.storage.sync.get(TWC_DEFAULTS, (stored) => apply(stored));
    });
  });
})();
