/* トレひろ – Trello ワイドカード / 設定ポップアップ */

(() => {
  const el = {
    body: document.body,
    enabled: document.getElementById("enabled"),
    enabledText: document.getElementById("enabledText"),
    cardWidth: document.getElementById("cardWidth"),
    cardWidthValue: document.getElementById("cardWidthValue"),
    descRatio: document.getElementById("descRatio"),
    ratioValue: document.getElementById("ratioValue"),
    previewLeft: document.getElementById("previewLeft"),
    reset: document.getElementById("reset"),
    saved: document.getElementById("saved"),
  };

  let savedTimer = null;

  /** UI にだけ反映（保存はしない） */
  function render(settings) {
    const s = twcNormalize(settings);

    el.enabled.checked = s.enabled;
    el.enabledText.textContent = s.enabled ? "ON" : "OFF";
    el.body.classList.toggle("is-off", !s.enabled);

    el.cardWidth.value = String(s.cardWidth);
    el.cardWidthValue.textContent = s.cardWidth + "%";

    el.descRatio.value = String(s.descRatio);
    el.ratioValue.textContent = s.descRatio + " : " + (100 - s.descRatio);
    el.previewLeft.style.flexBasis = s.descRatio + "%";
  }

  /** 現在の UI の値を設定オブジェクトとして取り出す */
  function collect() {
    return twcNormalize({
      enabled: el.enabled.checked,
      cardWidth: el.cardWidth.value,
      descRatio: el.descRatio.value,
    });
  }

  function flashSaved() {
    el.saved.classList.add("show");
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => el.saved.classList.remove("show"), 1200);
  }

  /** 保存する。content script が storage.onChanged を見ているので即座に反映される。 */
  function save() {
    const settings = collect();
    render(settings);
    chrome.storage.sync.set(settings, flashSaved);
  }

  // スライダーはドラッグ中もライブ反映（input）させたいので input で保存する。
  el.enabled.addEventListener("change", save);
  el.cardWidth.addEventListener("input", save);
  el.descRatio.addEventListener("input", save);

  el.reset.addEventListener("click", () => {
    render(TWC_DEFAULTS);
    chrome.storage.sync.set(TWC_DEFAULTS, flashSaved);
  });

  chrome.storage.sync.get(TWC_DEFAULTS, (stored) => render(stored));
})();
