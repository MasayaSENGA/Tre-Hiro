/*
 * トレひろ – ボードの各リストの見出しにリストIDを出す
 *
 * リストの枠（[data-testid="list-wrapper"]）が持つ data-list-id を、
 * 見出し（[data-testid="list-header"]）の最後にバッジとして足す。押すとIDをコピーする。
 */

(() => {
  "use strict";

  const BADGE = "data-twc-list-id";
  let observer = null;
  let scheduled = false;

  function makeBadge(listId) {
    const label = `ID: ${listId}`;
    let timer = 0;

    const badge = document.createElement("div");
    badge.setAttribute(BADGE, listId);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "twc-list-id";
    button.textContent = label;
    button.title = "リストIDをコピー";
    button.addEventListener("click", async (event) => {
      // 見出しのクリック（リスト名の編集など）に伝わらないようにする。
      event.preventDefault();
      event.stopPropagation();
      const copied = await twcCopyText(listId);
      button.textContent = copied ? "コピーしました" : "コピーできませんでした";
      button.dataset.copied = copied ? "true" : "false";
      clearTimeout(timer);
      timer = setTimeout(() => {
        button.textContent = label;
        delete button.dataset.copied;
      }, 1800);
    });
    badge.appendChild(button);
    return badge;
  }

  function addBadges() {
    for (const wrapper of document.querySelectorAll('[data-testid="list-wrapper"][data-list-id]')) {
      const listId = wrapper.getAttribute("data-list-id");
      const header = wrapper.querySelector('[data-testid="list-header"]');
      if (!listId || !header) continue;
      const badge = header.querySelector(`[${BADGE}]`);
      if (badge && badge.getAttribute(BADGE) === listId) continue;
      if (badge) badge.remove();
      header.appendChild(makeBadge(listId));
    }
  }

  // ボードの描画中は DOM の変化が続くので、1 フレームにまとめて処理する。
  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      if (observer) addBadges();
    });
  }

  function start() {
    if (observer) return;
    observer = new MutationObserver(schedule);
    observer.observe(document.documentElement, { childList: true, subtree: true });
    addBadges();
  }

  function apply(settings) {
    const s = twcNormalize(settings);
    if (s.enabled && s.listIds) start();
    else {
      if (observer) observer.disconnect();
      observer = null;
      document.querySelectorAll(`[${BADGE}]`).forEach((badge) => badge.remove());
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
    if (!["enabled", "listIds"].some((key) => key in changes)) return;
    whenReady(() => {
      chrome.storage.sync.get(TWC_DEFAULTS, (stored) => apply(stored));
    });
  });
})();
