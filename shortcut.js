/*
 * トレひろ – ショートカット「c」（カードのアーカイブ）を無効化する
 *
 * Trello より先にキー入力を受け取れるよう、document_start で window のキャプチャ段階に
 * 1 回だけ登録しておき、設定が OFF の間は何もしない。
 */

(() => {
  "use strict";

  const TOAST = "data-twc-shortcut-toast";
  let active = false;
  let toastTimer = 0;

  function isTyping() {
    const el = document.activeElement;
    return !!el && (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) || el.isContentEditable);
  }

  function showToast() {
    let toast = document.querySelector(`[${TOAST}]`);
    if (!toast) {
      toast = document.createElement("div");
      toast.setAttribute(TOAST, "");
      toast.setAttribute("role", "status");
      toast.textContent = "ショートカット「c」はトレひろにより無効化されています";
      document.body.appendChild(toast);
    }
    // 出し直しでもふわっと出るよう、表示の印は次のフレームで付ける。
    requestAnimationFrame(() => toast.setAttribute("data-shown", ""));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.removeAttribute("data-shown");
      setTimeout(() => {
        if (!toast.hasAttribute("data-shown")) toast.remove();
      }, 300);
    }, 2000);
  }

  window.addEventListener(
    "keydown",
    (event) => {
      if (!active) return;
      // CapsLock が有効だと Shift なしでも「C」になるため、大文字も対象にする。
      if (event.key !== "c" && event.key !== "C") return;
      if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      if (event.isComposing || isTyping()) return;
      event.stopImmediatePropagation();
      event.preventDefault();
      showToast();
    },
    true
  );

  function apply(settings) {
    const s = twcNormalize(settings);
    active = s.enabled && s.disableShortcutC;
    if (!active) document.querySelectorAll(`[${TOAST}]`).forEach((toast) => toast.remove());
  }

  chrome.storage.sync.get(TWC_DEFAULTS, (stored) => {
    apply(chrome.runtime.lastError ? TWC_DEFAULTS : stored);
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "sync") return;
    if (!["enabled", "disableShortcutC"].some((key) => key in changes)) return;
    chrome.storage.sync.get(TWC_DEFAULTS, (stored) => apply(stored));
  });
})();
