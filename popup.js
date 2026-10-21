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
    autoButtons: document.getElementById("autoButtons"),
    autoButtonsText: document.getElementById("autoButtonsText"),
    colorField: document.getElementById("colorField"),
    colorCards: document.getElementById("colorCards"),
    colorCardsText: document.getElementById("colorCardsText"),
    colorStrength: document.getElementById("colorStrength"),
    colorStrengthValue: document.getElementById("colorStrengthValue"),
    colorVibrancy: document.getElementById("colorVibrancy"),
    colorVibrancyValue: document.getElementById("colorVibrancyValue"),
    swatch: document.getElementById("swatch"),
    reset: document.getElementById("reset"),
    saved: document.getElementById("saved"),
  };

  let savedTimer = null;
  let rangeSaveTimer = null;
  let pendingSettings = null;
  let lastRangeSaveAt = 0;
  const RANGE_SAVE_INTERVAL = 1000;

  /* 色付けプレビュー。Trello の標準ラベル色から代表的なものを借りている。 */
  const SWATCHES = [
    { text: "緑", colors: ["#4bce97"] },
    { text: "赤", colors: ["#f87168"] },
    { text: "複数", colors: ["#9f8fef", "#f5cd47"] },
  ];

  /** colorize.js と同じ作り方の縦帯（ラベルが複数なら等分して積む）。 */
  function barGradient(colors) {
    if (colors.length === 1) return `linear-gradient(${colors[0]}, ${colors[0]})`;
    const step = 100 / colors.length;
    const stops = colors.map(
      (c, i) => `${c} ${(step * i).toFixed(2)}% ${(step * (i + 1)).toFixed(2)}%`
    );
    return `linear-gradient(to bottom, ${stops.join(", ")})`;
  }

  const swatchCards = SWATCHES.map((s) => {
    const span = document.createElement("span");
    span.className = "swatch-card";
    span.textContent = s.text;
    span.style.setProperty("--twc-bar", barGradient(s.colors));
    el.swatch.appendChild(span);
    return { span, color: s.colors[0], colors: s.colors };
  });

  function renderSwatches(strength, vibrancy) {
    for (const { span, color, colors } of swatchCards) {
      const adjusted = `hsl(from ${color} h calc(s * ${vibrancy / 100}) l)`;
      span.style.setProperty(
        "--twc-tint",
        `color-mix(in srgb, ${adjusted} ${strength}%, transparent)`
      );
      span.style.setProperty(
        "--twc-bar",
        barGradient(colors.map((c) => `hsl(from ${c} h calc(s * ${vibrancy / 100}) l)`))
      );
    }
  }

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

    el.autoButtons.checked = s.autoButtons;
    el.autoButtonsText.textContent = s.autoButtons ? "ON" : "OFF";

    el.colorCards.checked = s.colorCards;
    el.colorCardsText.textContent = s.colorCards ? "ON" : "OFF";
    el.colorField.classList.toggle("is-colors-off", !s.colorCards);
    el.colorStrength.value = String(s.colorStrength);
    el.colorStrengthValue.textContent = s.colorStrength + "%";
    el.colorVibrancy.value = String(s.colorVibrancy);
    el.colorVibrancyValue.textContent = s.colorVibrancy + "%";
    renderSwatches(s.colorStrength, s.colorVibrancy);
  }

  /** 現在の UI の値を設定オブジェクトとして取り出す */
  function collect() {
    return twcNormalize({
      enabled: el.enabled.checked,
      cardWidth: el.cardWidth.value,
      descRatio: el.descRatio.value,
      autoButtons: el.autoButtons.checked,
      colorCards: el.colorCards.checked,
      colorStrength: el.colorStrength.value,
      colorVibrancy: el.colorVibrancy.value,
    });
  }

  function flashSaved() {
    el.saved.classList.add("show");
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => el.saved.classList.remove("show"), 1200);
  }

  /** 保存する。content script が storage.onChanged を見ているので即座に反映される。 */
  function save() {
    clearTimeout(rangeSaveTimer);
    rangeSaveTimer = null;
    pendingSettings = null;
    const settings = collect();
    render(settings);
    chrome.storage.sync.set(settings, flashSaved);
  }

  /** ドラッグ中はプレビューを即時更新し、ストレージ書き込みは毎秒までに抑える。 */
  function saveRange() {
    pendingSettings = collect();
    render(pendingSettings);
    clearTimeout(rangeSaveTimer);
    rangeSaveTimer = setTimeout(flushRangeSave, RANGE_SAVE_INTERVAL);
  }

  /** 操作後の最終値を保存する。連続操作中も書き込み間隔を空ける。 */
  function flushRangeSave() {
    clearTimeout(rangeSaveTimer);
    rangeSaveTimer = null;
    if (!pendingSettings) return;
    const wait = RANGE_SAVE_INTERVAL - (Date.now() - lastRangeSaveAt);
    if (wait > 0) {
      rangeSaveTimer = setTimeout(flushRangeSave, wait);
      return;
    }
    const settings = pendingSettings;
    pendingSettings = null;
    lastRangeSaveAt = Date.now();
    chrome.storage.sync.set(settings, flashSaved);
  }

  // スライダーはプレビューを即時更新し、設定の保存は最大毎秒に間引く。
  el.enabled.addEventListener("change", save);
  for (const input of [el.cardWidth, el.descRatio, el.colorStrength, el.colorVibrancy]) {
    input.addEventListener("input", saveRange);
    input.addEventListener("change", flushRangeSave);
  }
  el.autoButtons.addEventListener("change", save);
  el.colorCards.addEventListener("change", save);

  el.reset.addEventListener("click", () => {
    clearTimeout(rangeSaveTimer);
    rangeSaveTimer = null;
    pendingSettings = null;
    render(TWC_DEFAULTS);
    chrome.storage.sync.set(TWC_DEFAULTS, flashSaved);
  });

  chrome.storage.sync.get(TWC_DEFAULTS, (stored) => render(stored));
})();
