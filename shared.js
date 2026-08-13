/* トレひろ – 設定の既定値と共通ユーティリティ（content script / popup 共用） */

const TWC_DEFAULTS = {
  enabled: true,
  cardWidth: 95, // カード幅（ウィンドウ幅に対する %）
  descRatio: 60, // 左カラム＝説明欄の割合（%）。残りがコメント欄。
  colorCards: true, // ボードのカードをラベル色で塗るか
  colorStrength: 16, // 背景に重ねるラベル色の濃さ（%）
};

const TWC_LIMITS = {
  cardWidth: { min: 40, max: 100 },
  descRatio: { min: 15, max: 90 },
  colorStrength: { min: 5, max: 45 },
};

function twcClamp(value, min, max, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.round(n)));
}

/** 保存値を検証して、必ず有効な設定オブジェクトを返す。 */
function twcNormalize(stored) {
  const s = stored || {};
  return {
    enabled: s.enabled !== false,
    cardWidth: twcClamp(
      s.cardWidth,
      TWC_LIMITS.cardWidth.min,
      TWC_LIMITS.cardWidth.max,
      TWC_DEFAULTS.cardWidth
    ),
    descRatio: twcClamp(
      s.descRatio,
      TWC_LIMITS.descRatio.min,
      TWC_LIMITS.descRatio.max,
      TWC_DEFAULTS.descRatio
    ),
    colorCards: s.colorCards !== false,
    colorStrength: twcClamp(
      s.colorStrength,
      TWC_LIMITS.colorStrength.min,
      TWC_LIMITS.colorStrength.max,
      TWC_DEFAULTS.colorStrength
    ),
  };
}
