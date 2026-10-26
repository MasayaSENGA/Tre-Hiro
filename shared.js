/* トレひろ – 設定の既定値と共通ユーティリティ（content script / popup 共用） */

const TWC_DEFAULTS = {
  enabled: true,
  cardWidth: 95, // カード幅（ウィンドウ幅に対する %）
  descRatio: 40, // 左カラム＝説明欄の割合（%）。残りがコメント欄。
  colorCards: true, // ボードのカードをラベル色で塗るか
  colorStrength: 45, // 背景に重ねるラベル色の濃さ（%）
  colorVibrancy: 100, // ラベル色の鮮やかさ（%）
  autoButtons: true, // カード詳細の下部に自動化（カードボタン）を常に並べるか
  listIds: true, // ボードの各リストの見出しにリストIDを出すか
  cardHistory: true, // カード詳細のヘッダーに変更履歴（JSON）を開くボタンを置くか
  disableShortcutC: false, // ショートカット「c」（カードのアーカイブ）を無効化するか
};

const TWC_LIMITS = {
  cardWidth: { min: 40, max: 100 },
  descRatio: { min: 15, max: 90 },
  colorStrength: { min: 5, max: 45 },
  colorVibrancy: { min: 0, max: 200 },
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
    colorVibrancy: twcClamp(
      s.colorVibrancy,
      TWC_LIMITS.colorVibrancy.min,
      TWC_LIMITS.colorVibrancy.max,
      TWC_DEFAULTS.colorVibrancy
    ),
    autoButtons: s.autoButtons !== false,
    listIds: s.listIds !== false,
    cardHistory: s.cardHistory !== false,
    disableShortcutC: s.disableShortcutC === true,
  };
}

/** 文字列をクリップボードにコピーし、できたかどうかを返す。 */
async function twcCopyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API が使えない環境では、クリック中のユーザー操作でコピーする。
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } finally {
      field.remove();
    }
    return copied;
  }
}
