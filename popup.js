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
    ratioRightValue: document.getElementById("ratioRightValue"),
    previewLeft: document.getElementById("previewLeft"),
    autoButtons: document.getElementById("autoButtons"),
    autoButtonsText: document.getElementById("autoButtonsText"),
    listIds: document.getElementById("listIds"),
    listIdsText: document.getElementById("listIdsText"),
    cardHistory: document.getElementById("cardHistory"),
    cardHistoryText: document.getElementById("cardHistoryText"),
    disableShortcutC: document.getElementById("disableShortcutC"),
    disableShortcutCText: document.getElementById("disableShortcutCText"),
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
  const VIBRANCY_DETENT = 4;

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
    el.cardWidthValue.value = String(s.cardWidth);

    el.descRatio.value = String(s.descRatio);
    el.ratioValue.value = String(s.descRatio);
    el.ratioRightValue.value = String(100 - s.descRatio);
    el.previewLeft.style.flexBasis = s.descRatio + "%";

    el.autoButtons.checked = s.autoButtons;
    el.autoButtonsText.textContent = s.autoButtons ? "ON" : "OFF";

    el.listIds.checked = s.listIds;
    el.listIdsText.textContent = s.listIds ? "ON" : "OFF";
    el.cardHistory.checked = s.cardHistory;
    el.cardHistoryText.textContent = s.cardHistory ? "ON" : "OFF";
    el.disableShortcutC.checked = s.disableShortcutC;
    el.disableShortcutCText.textContent = s.disableShortcutC ? "ON" : "OFF";

    el.colorCards.checked = s.colorCards;
    el.colorCardsText.textContent = s.colorCards ? "ON" : "OFF";
    el.colorField.classList.toggle("is-colors-off", !s.colorCards);
    el.colorStrength.value = String(s.colorStrength);
    el.colorStrengthValue.value = String(s.colorStrength);
    el.colorVibrancy.value = String(s.colorVibrancy);
    el.colorVibrancyValue.value = String(s.colorVibrancy);
    renderSwatches(s.colorStrength, s.colorVibrancy);
  }

  /** 現在の UI の値を設定オブジェクトとして取り出す */
  function collect() {
    return twcNormalize({
      enabled: el.enabled.checked,
      cardWidth: el.cardWidth.value,
      descRatio: el.descRatio.value,
      autoButtons: el.autoButtons.checked,
      listIds: el.listIds.checked,
      cardHistory: el.cardHistory.checked,
      disableShortcutC: el.disableShortcutC.checked,
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
    const vibrancy = Number(el.colorVibrancy.value);
    if (Math.abs(vibrancy - 100) <= VIBRANCY_DETENT) {
      el.colorVibrancy.value = "100";
    }
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
  el.listIds.addEventListener("change", save);
  el.cardHistory.addEventListener("change", save);
  el.disableShortcutC.addEventListener("change", save);
  el.colorCards.addEventListener("change", save);

  const numberInputs = [
    [el.cardWidthValue, el.cardWidth, TWC_LIMITS.cardWidth],
    [el.colorStrengthValue, el.colorStrength, TWC_LIMITS.colorStrength],
    [el.colorVibrancyValue, el.colorVibrancy, TWC_LIMITS.colorVibrancy],
  ];
  for (const [numberInput, rangeInput, limits] of numberInputs) {
    numberInput.addEventListener("change", () => {
      const value = twcClamp(numberInput.value, limits.min, limits.max, Number(rangeInput.value));
      rangeInput.value = String(value);
      numberInput.value = String(value);
      save();
    });
    numberInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") numberInput.blur();
    });
  }

  for (const [numberInput, toDescRatio] of [
    [el.ratioValue, (value) => value],
    [el.ratioRightValue, (value) => 100 - value],
  ]) {
    numberInput.addEventListener("change", () => {
      const entered = Number(numberInput.value);
      const fallback = Number(el.descRatio.value);
      const value = twcClamp(
        toDescRatio(Number.isFinite(entered) ? entered : (numberInput === el.ratioValue ? fallback : 100 - fallback)),
        TWC_LIMITS.descRatio.min,
        TWC_LIMITS.descRatio.max,
        fallback
      );
      el.descRatio.value = String(value);
      save();
    });
    numberInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") numberInput.blur();
    });
  }

  el.reset.addEventListener("click", () => {
    clearTimeout(rangeSaveTimer);
    rangeSaveTimer = null;
    pendingSettings = null;
    render(TWC_DEFAULTS);
    chrome.storage.sync.set(TWC_DEFAULTS, flashSaved);
  });

  chrome.storage.sync.get(TWC_DEFAULTS, (stored) => render(stored));
})();
