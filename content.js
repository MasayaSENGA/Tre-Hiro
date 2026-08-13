/*
 * トレひろ – Trello ワイドカード / content script
 *
 * やっていることは 2 つだけ:
 *   1. 保存された設定を CSS 変数（--twc-card-width / --twc-desc-ratio）に流し込む
 *   2. 有効フラグを html[data-twc-on] として付ける（content.css 側の適用スイッチ）
 *
 * DOM は一切書き換えないので、Trello の React 描画とは干渉しない。
 */

(() => {
  const root = document.documentElement;

  function applySettings(settings) {
    const s = twcNormalize(settings);

    root.style.setProperty("--twc-card-width", s.cardWidth + "vw");
    // 100% 指定でもスクロールバー分がはみ出さないように上限を付ける
    root.style.setProperty(
      "--twc-card-max-width",
      s.cardWidth >= 100 ? "calc(100vw - 8px)" : "calc(100vw - 24px)"
    );
    root.style.setProperty("--twc-desc-ratio", s.descRatio + "%");
    root.style.setProperty("--twc-color-strength", s.colorStrength + "%");

    if (s.enabled) {
      root.setAttribute("data-twc-on", "");
    } else {
      root.removeAttribute("data-twc-on");
    }

    // カードの色付けは独立して ON/OFF できる（塗る対象の抽出は colorize.js 側）。
    if (s.colorCards) {
      root.setAttribute("data-twc-color", "");
    } else {
      root.removeAttribute("data-twc-color");
    }
  }

  chrome.storage.sync.get(TWC_DEFAULTS, (stored) => {
    if (chrome.runtime.lastError) {
      applySettings(TWC_DEFAULTS);
      return;
    }
    applySettings(stored);
  });

  // ポップアップで値を動かした瞬間に、開いているタブへ反映する。
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "sync") return;
    const touched = [
      "enabled",
      "cardWidth",
      "descRatio",
      "colorCards",
      "colorStrength",
    ].some((key) => key in changes);
    if (!touched) return;
    chrome.storage.sync.get(TWC_DEFAULTS, (stored) => applySettings(stored));
  });
})();
