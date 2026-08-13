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
    colorField: document.getElementById("colorField"),
    colorCards: document.getElementById("colorCards"),
    colorCardsText: document.getElementById("colorCardsText"),
    colorStrength: document.getElementById("colorStrength"),
    colorStrengthValue: document.getElementById("colorStrengthValue"),
    swatch: document.getElementById("swatch"),
    reset: document.getElementById("reset"),
    saved: document.getElementById("saved"),
  };

  let savedTimer = null;

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
    return { span, color: s.colors[0] };
  });

  function renderSwatches(strength) {
    for (const { span, color } of swatchCards) {
      span.style.setProperty(
        "--twc-tint",
        `color-mix(in srgb, ${color} ${strength}%, transparent)`
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

    el.colorCards.checked = s.colorCards;
    el.colorCardsText.textContent = s.colorCards ? "ON" : "OFF";
    el.colorField.classList.toggle("is-colors-off", !s.colorCards);
    el.colorStrength.value = String(s.colorStrength);
    el.colorStrengthValue.textContent = s.colorStrength + "%";
    renderSwatches(s.colorStrength);
  }

  /** 現在の UI の値を設定オブジェクトとして取り出す */
  function collect() {
    return twcNormalize({
      enabled: el.enabled.checked,
      cardWidth: el.cardWidth.value,
      descRatio: el.descRatio.value,
      colorCards: el.colorCards.checked,
      colorStrength: el.colorStrength.value,
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
  el.colorCards.addEventListener("change", save);
  el.colorStrength.addEventListener("input", save);

  el.reset.addEventListener("click", () => {
    render(TWC_DEFAULTS);
    chrome.storage.sync.set(TWC_DEFAULTS, flashSaved);
  });

  chrome.storage.sync.get(TWC_DEFAULTS, (stored) => render(stored));
})();
