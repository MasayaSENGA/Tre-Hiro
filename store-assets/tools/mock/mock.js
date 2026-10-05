/*
 * トレひろ ストア素材用「Trello の再現ページ（模型）」の描画スクリプト。
 *
 * 本物の Trello と同じく、ページを開いた後に JavaScript でボードとカード詳細を組み立てる。
 * 内容はすべて架空（ボード「Webサイト リニューアル」、メンバー 佐藤 美咲／鈴木 健／高橋 さくら）。
 * アイコンはすべてここで描いた簡単な SVG（Trello / Atlassian のアイコンは使っていない）。
 *
 * このスクリプトはトレひろが付ける印（拡張専用の data 属性や CSS 変数）を一切書かない・読まない。
 * 幅の拡張や色付けは、撮影時に読み込んだ本物の拡張機能だけが行う
 * （capture_raw.py は、このフォルダのファイルに拡張の印の名前が出てこないことも確かめる）。
 *
 * <body data-view="board"> … ボードだけ（/b/<id>/<slug>）
 * <body data-view="card">  … ボードの上にカード詳細を開いた状態（/c/<id>/<slug>）
 */
(() => {
  "use strict";

  /* ------------------------------------------------------------------
     自作アイコン（24×24、線で描く）
     ------------------------------------------------------------------ */
  const PATHS = {
    desc: '<path d="M4 6h16M4 12h16M4 18h10"/>',
    checklist: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8.5 12.5l2.5 2.5 4.5-5.5"/>',
    comment:
      '<path d="M5 5h14a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-8l-4 3v-3H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z"/><path d="M8 9.5h8M8 13h5"/>',
    clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4.5l3 1.8"/>',
    clip: '<path d="M16.5 7.5l-7 7a2 2 0 0 0 2.8 2.8l7.2-7.2a4 4 0 0 0-5.7-5.7l-7.4 7.4a6 6 0 0 0 8.5 8.5l6.1-6.1"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    chevron: '<path d="M7 10l5 5 5-5"/>',
    close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    dots: '<circle cx="6" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18" cy="12" r="1.3" fill="currentColor"/>',
    eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    image: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M20.5 15.5l-4.5-4.5-8 8"/>',
    plug: '<path d="M9 3.5v4.5M15 3.5v4.5M6.5 8h11v3.5a5.5 5.5 0 0 1-11 0z"/><path d="M12 17v3.5"/>',
    bolt: '<path d="M13.5 3L5.5 13.5h6l-1 7.5 8-10.5h-6z"/>',
    filter: '<path d="M4 6.5h16M7 12h10M10 17.5h4"/>',
    star: '<path d="M12 4l2.4 5 5.4.6-4 3.7 1.1 5.4L12 16l-4.9 2.7 1.1-5.4-4-3.7 5.4-.6z"/>',
    people:
      '<circle cx="9" cy="8.5" r="3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0"/><path d="M15.5 5.6a3 3 0 0 1 0 5.8M17.5 14a5.5 5.5 0 0 1 3 5"/>',
    share: '<circle cx="10" cy="8" r="3.5"/><path d="M3.5 20a6.5 6.5 0 0 1 13 0"/><path d="M19 8v6M16 11h6"/>',
    boardView: '<rect x="4" y="5" width="4.5" height="14" rx="1"/><rect x="10" y="5" width="4.5" height="9" rx="1"/><rect x="16" y="5" width="4" height="11" rx="1"/>',
    template: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 10h8M8 14h5"/>',
    collapse: '<path d="M5 5v14M19 12H9M13 8l-4 4 4 4"/>',
    check: '<path d="M6.5 12.5l3.5 3.5 7.5-8"/>',
    tag: '<path d="M4 4.5h7.2l8.3 8.3a1.5 1.5 0 0 1 0 2.1l-4.6 4.6a1.5 1.5 0 0 1-2.1 0L4.5 11.2V4.5z"/><circle cx="8.5" cy="8.5" r="1.4"/>',
    rocket: '<path d="M12 3c3 2 4.5 5 4.5 9l-2 3h-5l-2-3C7.5 8 9 5 12 3z"/><circle cx="12" cy="9.5" r="1.5"/><path d="M9.5 15l-2 3.5M14.5 15l2 3.5"/>',
  };

  function icon(name, size = 16, stroke = 2) {
    return (
      `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
      `stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name]}</svg>`
    );
  }

  const esc = (s) =>
    String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  /* ------------------------------------------------------------------
     架空のデータ
     ------------------------------------------------------------------ */
  const MEMBERS = {
    sato: { name: "佐藤 美咲", initial: "佐", color: "#5e4db2" },
    suzuki: { name: "鈴木 健", initial: "鈴", color: "#206a83" },
    takahashi: { name: "高橋 さくら", initial: "高", color: "#a54800" },
  };
  const ME = "sato"; // ログインしている人（コメント入力欄のアバター）

  // Trello の標準ラベル色（調査 §2.5 の背景色・文字色）
  const COLORS = {
    green: { bg: "#4BCE97", fg: "#164B35", ja: "グリーン" },
    yellow: { bg: "#EED12B", fg: "#533F04", ja: "イエロー" },
    orange: { bg: "#FCA700", fg: "#693200", ja: "オレンジ" },
    red: { bg: "#F87168", fg: "#5D1F1A", ja: "レッド" },
    purple: { bg: "#C97CF4", fg: "#48245D", ja: "パープル" },
    blue: { bg: "#669DF1", fg: "#123263", ja: "ブルー" },
  };
  const LABELS = {
    design: { color: "green", name: "デザイン" },
    copy: { color: "yellow", name: "原稿" },
    check: { color: "orange", name: "確認" },
    urgent: { color: "red", name: "至急" },
    dev: { color: "purple", name: "開発" },
    release: { color: "blue", name: "公開準備" },
  };

  const BOARD = {
    id: "Mk7Wb2Qa",
    slug: "web-renewal",
    name: "Webサイト リニューアル",
    lists: [
      {
        name: "未着手",
        cards: [
          { id: "Qw3nB7xR", n: 3, slug: "contact-form", title: "お問い合わせフォームの項目を整理する",
            labels: ["dev", "copy"], desc: true, checklist: [0, 4] },
          { id: "Lm5vK2pZ", n: 5, slug: "recruit-copy", title: "採用情報ページの原稿を依頼する",
            labels: ["copy"], due: { text: "10月16日" }, comments: 2, members: ["takahashi"] },
          { id: "Yt9hD4sF", n: 7, slug: "ogp-image", title: "OGP 画像を作成する",
            labels: ["design", "release"], desc: true, attachments: 1 },
          { id: "Pk2rW8nC", n: 9, slug: "sitemap", title: "サイトマップを最新にする", labels: [], desc: true },
        ],
      },
      {
        name: "作業中",
        cards: [
          { id: "Hr8dT0pK", n: 14, slug: "top-page-design", title: "トップページのデザインを確定する",
            labels: ["design", "check"], due: { text: "10月9日" }, desc: true, comments: 4,
            checklist: [3, 5], members: ["sato", "suzuki", "takahashi"], hero: true },
          { id: "Gx6mQ1vT", n: 15, slug: "news-list", title: "お知らせ一覧の表示を改修する",
            labels: ["dev"], desc: true, checklist: [2, 6], members: ["suzuki"] },
          { id: "Nc4tH9wE", n: 16, slug: "company-photos", title: "会社概要ページの写真を差し替える",
            labels: ["design", "copy", "urgent"], due: { text: "10月5日", state: "soon" }, attachments: 3,
            members: ["sato"] },
        ],
      },
      {
        name: "確認待ち",
        cards: [
          { id: "Vb7kS3qM", n: 11, slug: "mobile-layout", title: "スマホ表示の崩れを修正する",
            labels: ["urgent", "dev"], comments: 3, checklist: [4, 4], members: ["suzuki"] },
          { id: "Rj2yF6dA", n: 12, slug: "privacy-wording", title: "プライバシーポリシーの文言を確認する",
            labels: ["check"], desc: true, attachments: 1, members: ["takahashi"] },
          { id: "Zs8pL5gU", n: 13, slug: "favicon", title: "ファビコンを差し替える", labels: [] },
        ],
      },
      {
        name: "完了",
        cards: [
          { id: "Dw1cX7hJ", n: 4, slug: "redirect-list", title: "旧ページのリダイレクト一覧を作る",
            labels: ["dev", "release"], desc: true, checklist: [6, 6] },
          { id: "Fe3gN8bY", n: 2, slug: "schedule", title: "公開スケジュールを決める",
            labels: ["release"], desc: true, comments: 5 },
          { id: "Ku6aV2mR", n: 1, slug: "kickoff", title: "キックオフミーティング", labels: [], desc: true,
            attachments: 2 },
        ],
      },
    ],
  };

  // 主役のカードの中身
  const HERO_DETAIL = {
    due: "2026/10/09 18:00",
    description: `
      <p>トップページのリニューアル案（デザイン案 B）を確定するためのカードです。各パーツの確認状況を下の表にまとめています。</p>
      <p>公開予定日は <strong>10 月 20 日（火）</strong>です。すべての項目が「完了」になったら、このカードを「確認待ち」リストへ移動してください。</p>
      <div class="pm-table-container" data-testid="mock-description-table">
        <table>
          <thead>
            <tr><th>確認項目</th><th>担当</th><th>期限</th><th>状態</th><th>メモ</th></tr>
          </thead>
          <tbody>
            <tr><td>ファーストビューの見出し</td><td>高橋 さくら</td><td>10/06（火）</td><td><span class="status-lozenge is-done">完了</span></td><td>案 B の文言で確定済み</td></tr>
            <tr><td>ヒーロー画像（PC・スマホ）</td><td>佐藤 美咲</td><td>10/07（水）</td><td><span class="status-lozenge is-progress">確認中</span></td><td>スマホで顔が切れないよう調整</td></tr>
            <tr><td>グローバルナビの並び順</td><td>鈴木 健</td><td>10/08（木）</td><td><span class="status-lozenge is-progress">確認中</span></td><td>「採用情報」を右端へ移す案</td></tr>
            <tr><td>お知らせ欄の表示件数</td><td>高橋 さくら</td><td>10/08（木）</td><td><span class="status-lozenge is-todo">未着手</span></td><td>3 件表示＋一覧リンクで仮置き</td></tr>
            <tr><td>フッターの著作権表記</td><td>鈴木 健</td><td>10/09（金）</td><td><span class="status-lozenge is-todo">未着手</span></td><td>年号を自動で更新する</td></tr>
          </tbody>
        </table>
      </div>
      <ul>
        <li><p>デザインデータは共有フォルダの「02_デザイン／トップ」にあります。</p></li>
        <li><p>確認は PC とスマホの両方で行い、結果を表の「状態」に記入してください。</p></li>
        <li><p>文言の変更は、このカードのコメントで相談しましょう。</p></li>
      </ul>`,
    checklist: {
      title: "公開前チェック",
      items: [
        ["PC・スマホで表示崩れがないか確認", true],
        ["リンク切れがないか確認", true],
        ["画像の代替テキストを設定", true],
        ["ページの表示速度を計測", false],
        ["公開日時の最終確認", false],
      ],
    },
    // 新しい順。kind: comment / activity
    actions: [
      { kind: "comment", who: "takahashi", date: "2026/10/05 9:42",
        text: "見出しは案 B の文言で確定しました。表の「状態」も更新してあります。" },
      { kind: "comment", who: "suzuki", date: "2026/10/02 17:10",
        text: "スマホ表示も確認しました。ヒーロー画像の人物が少し切れるので、位置の調整をお願いします。" },
      { kind: "activity", who: "suzuki", date: "2026/10/02 16:55",
        text: "さんがこのカードの期限を2026/10/09 18:00に設定しました。" },
      { kind: "comment", who: "sato", date: "2026/10/02 11:05",
        text: "デザイン案 B の確認項目を説明欄の表にまとめました。金曜までに確認をお願いします！" },
      { kind: "comment", who: "takahashi", date: "2026/10/01 10:12",
        text: "お知らせ欄は 3 件表示で良さそうです。" },
      { kind: "activity", who: "sato", date: "2026/10/01 9:30",
        text: "さんがこのカードを 未着手 リストから 作業中 リストに移動しました。" },
    ],
  };

  const cardUrl = (c) => `/c/${c.id}/${c.n}-${c.slug}`;
  const boardUrl = () => `/b/${BOARD.id}/${BOARD.slug}`;

  function avatar(key, size) {
    const m = MEMBERS[key];
    const cls = size ? ` is-${size}` : "";
    return `<span class="avatar${cls}" style="background-color:${m.color}" title="${esc(m.name)}" aria-label="${esc(m.name)}">${esc(m.initial)}</span>`;
  }

  /* ------------------------------------------------------------------
     ボード
     ------------------------------------------------------------------ */
  function labelChip(key) {
    const l = LABELS[key];
    const c = COLORS[l.color];
    return (
      `<div><button type="button" data-testid="compact-card-label" data-color="${l.color}" data-expanded="false" ` +
      `class="color-blind-pattern-${l.color}" style="background-color:${c.bg}" ` +
      `aria-label="色: ${c.ja}、タイトル: 「${esc(l.name)}」">${esc(l.name)}</button></div>`
    );
  }

  function badges(c) {
    const out = [];
    if (c.due) {
      const cls = c.due.state === "soon" ? " is-due-soon" : c.due.state === "overdue" ? " is-overdue" : "";
      const tid = c.due.state ? "badge-due-date-not-completed" : "badge-due-date";
      out.push(`<span class="badge${cls}" data-testid="${tid}"><span class="badge-icon">${icon("clock", 14)}</span><span class="badge-text">${esc(c.due.text)}</span></span>`);
    }
    if (c.desc) {
      out.push(`<span class="badge" data-testid="badge-card-description" role="img" aria-label="このカードには詳細説明があります。"><span class="badge-icon">${icon("desc", 16)}</span></span>`);
    }
    if (c.comments) {
      out.push(`<span class="badge" data-testid="badge-comments" aria-label="コメント ${c.comments} 件"><span class="badge-icon">${icon("comment", 16)}</span><span class="badge-text">${c.comments}</span></span>`);
    }
    if (c.attachments) {
      out.push(`<span class="badge" data-testid="badge-attachments" aria-label="添付ファイル ${c.attachments} 件"><span class="badge-icon">${icon("clip", 15)}</span><span class="badge-text">${c.attachments}</span></span>`);
    }
    if (c.checklist) {
      const [done, total] = c.checklist;
      const cls = done === total ? " is-complete" : "";
      out.push(`<button type="button" class="badge${cls}" data-testid="checklist-badge" aria-label="${total} 件のチェックリスト項目のうち ${done} 件が完了しました"><span class="badge-icon">${icon("checklist", 15)}</span><span class="badge-text">${done}/${total}</span></button>`);
    }
    if (c.members && c.members.length) {
      out.push(`<div class="card-members" data-testid="card-front-members">${c.members.map((m) => avatar(m, 24)).join("")}</div>`);
    }
    if (!out.length) return "";
    return `<div data-testid="card-front-badges">${out.join("")}</div>`;
  }

  function cardFront(c) {
    const labels = c.labels.length ? `<div class="card-labels">${c.labels.map(labelChip).join("")}</div>` : "";
    return `
      <li data-testid="list-card" data-mock-card="${c.id}">
        <div>
          <div data-testid="list-card-wrapper">
            <div data-testid="trello-card" data-mock-href="${cardUrl(c)}">
              <div>
                <div>
                  ${labels}
                  <a data-testid="card-name" href="${cardUrl(c)}" dir="auto">${esc(c.title)}</a>
                  ${badges(c)}
                </div>
              </div>
              <div></div>
            </div>
          </div>
        </div>
      </li>`;
  }

  function list(l) {
    return `
      <li data-testid="list-wrapper">
        <div data-testid="list">
          <div data-testid="list-header">
            <div><h2 data-testid="list-name"><button type="button"><span>${esc(l.name)}</span></button></h2></div>
            <div><div role="presentation"><span class="list-count">${l.cards.length}</span></div></div>
            <button type="button" class="list-icon-btn" data-testid="list-collapse-button" aria-label="リストを折りたたむ">${icon("collapse", 16)}</button>
            <button type="button" class="list-icon-btn" data-testid="list-edit-menu-button" aria-label="リストの操作">${icon("dots", 16)}</button>
          </div>
          <div data-testid="list-card-gap"></div>
          <ol data-testid="list-cards">${l.cards.map(cardFront).join("")}</ol>
          <div class="list-footer" data-testid="list-footer">
            <button type="button" class="list-add-card" data-testid="list-add-card-button">${icon("plus", 16)}<span>カードを追加</span></button>
            <button type="button" class="list-icon-btn" aria-label="テンプレートから作成">${icon("template", 16)}</button>
          </div>
        </div>
      </li>`;
  }

  function boardView() {
    return `
      <div data-testid="board-view">
        <div data-testid="board-header" class="board-header">
          <div class="board-header-inner">
            <h1 data-testid="board-name-display">${esc(BOARD.name)}</h1>
            <button type="button" class="bh-view-btn" aria-label="ビュー">${icon("boardView", 16)}${icon("chevron", 16)}</button>
          </div>
          <div class="board-header-right">
            <div class="bh-members">${["sato", "suzuki", "takahashi"].map((m) => avatar(m, 28)).join("")}</div>
            <button type="button" class="bh-icon-btn" aria-label="Power-Up">${icon("rocket", 16)}</button>
            <button type="button" class="bh-icon-btn" aria-label="自動化">${icon("bolt", 16)}</button>
            <button type="button" class="bh-icon-btn" data-testid="filter-popover-button" aria-label="カードをフィルター">${icon("filter", 16)}</button>
            <button type="button" class="bh-icon-btn" aria-label="ボードにスターを付ける">${icon("star", 16)}</button>
            <button type="button" class="bh-icon-btn" aria-label="ワークスペースで表示">${icon("people", 16)}</button>
            <button type="button" class="bh-share" aria-label="ボードを共有">${icon("share", 16)}<span>共有</span></button>
            <button type="button" class="bh-icon-btn" aria-label="ボードメニューを表示">${icon("dots", 16)}</button>
          </div>
        </div>
        <div data-testid="board-canvas">
          <ul id="board" data-testid="lists">
            ${BOARD.lists.map(list).join("")}
            <li data-testid="list-wrapper"><button type="button" class="list-add-another">${icon("plus", 16)}<span>もう 1 つリストを追加</span></button></li>
          </ul>
        </div>
      </div>`;
  }

  /* ------------------------------------------------------------------
     カード詳細（カードバック）
     ------------------------------------------------------------------ */
  function findCard(id) {
    for (const l of BOARD.lists) {
      for (const c of l.cards) if (c.id === id) return { card: c, list: l };
    }
    return null;
  }

  function cardBackLabel(key) {
    const l = LABELS[key];
    const c = COLORS[l.color];
    return `<span data-testid="card-label" data-color="${l.color}" style="background-color:${c.bg};color:${c.fg}">${esc(l.name)}</span>`;
  }

  function actionItem(a) {
    const m = MEMBERS[a.who];
    if (a.kind === "activity") {
      return `
        <li data-testid="card-back-action">
          <div>${avatar(a.who)}</div>
          <div data-testid="card-back-action-container">
            <div class="cb-action-head is-activity"><span class="who">${esc(m.name)}</span><span class="what">${esc(a.text)}</span>
              <a class="cb-action-date" href="#action">${esc(a.date)}</a></div>
          </div>
        </li>`;
    }
    const own = a.who === ME
      ? `<div class="cb-comment-tools"><span class="link">編集</span><span class="link">削除</span></div>`
      : "";
    return `
      <li data-testid="card-back-action">
        <div>${avatar(a.who)}</div>
        <div data-testid="card-back-action-container">
          <div class="cb-action-head"><span class="who">${esc(m.name)}さんがコメントしました。</span>
            <a class="cb-action-date" href="#comment">${esc(a.date)}</a></div>
          <div role="button"><div data-testid="comment-container"><div><p>${esc(a.text)}</p></div></div></div>
          ${own}
        </div>
      </li>`;
  }

  function cardBack(found) {
    const { card, list: l } = found;
    const d = card.hero ? HERO_DETAIL : { description: "", actions: [] };
    const members = (card.members || []).map((m) => avatar(m)).join("");
    const meta = [];
    if (card.members && card.members.length) {
      meta.push(`<section><h3>メンバー</h3><div role="group">${members}<button type="button" class="cb-btn is-icon" style="border-radius:9999px" aria-label="メンバーを追加">${icon("plus", 16)}</button></div></section>`);
    }
    if (card.labels.length) {
      meta.push(`<section><h3>ラベル</h3><div role="group"><div data-testid="card-back-labels-container" style="display:flex;flex-wrap:wrap;gap:4px">${card.labels.map(cardBackLabel).join("")}<button type="button" class="cb-btn is-icon" aria-label="ラベルを追加">${icon("plus", 16)}</button></div></div></section>`);
    }
    if (d.due) {
      meta.push(`<section><h3>期限</h3><div role="group"><div data-testid="due-date-badge-checkbox"><div class="cb-due"><span class="cb-checkbox"></span><span>${esc(d.due)}</span>${icon("chevron", 16)}</div></div></div></section>`);
    }

    const description = d.description
      ? `<div data-testid="description-content-area"><div class="ak-renderer-wrapper is-full-width"><div class="ak-renderer-document">${d.description}</div></div></div>`
      : `<div data-testid="description-content-area"><p style="color:var(--ds-text-subtle)">詳しい説明を追加…</p></div>`;

    let checklist = "";
    if (d.checklist) {
      const done = d.checklist.items.filter((i) => i[1]).length;
      const pct = Math.round((done / d.checklist.items.length) * 100);
      checklist = `
        <div data-testid="checklist-container">
          <section data-testid="checklist-section" class="cb-section">
            <div class="cb-section-icon">${icon("checklist", 20)}</div>
            <hgroup>
              <h3 data-testid="checklist-title"><button type="button"><span>${esc(d.checklist.title)}</span></button></h3>
              <div class="cb-section-actions">
                <button type="button" class="cb-btn">完了したアイテムを非表示</button>
                <button type="button" class="cb-btn">削除</button>
              </div>
            </hgroup>
            <div class="cl-progress cb-full">
              <span data-testid="checklist-progress-percentage">${pct}%</span>
              <div data-testid="progress-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></div>
            </div>
            <ul data-testid="checklist-items" class="cb-full">
              ${d.checklist.items
                .map(
                  ([name, ok]) => `
                <li data-testid="check-item-container" class="${ok ? "is-done" : ""}">
                  <label data-testid="clickable-checkbox"><span class="cb-checkbox${ok ? " is-checked" : ""}">${ok ? icon("check", 14, 3) : ""}</span></label>
                  <div data-testid="check-item-name"><p>${esc(name)}</p></div>
                </li>`
                )
                .join("")}
            </ul>
            <div class="cb-body-col"><button type="button" class="cb-btn">アイテムを追加</button></div>
          </section>
        </div>`;
    }

    return `
      <div id="layer-manager-card-back">
        <div class="card-back-overlay" data-testid="card-back-overlay">
          <div id="overlay-contents">
            <div style="width:1px;height:0"></div>
            <div>
              <div role="dialog" data-testid="card-back-name" aria-modal="true" aria-labelledby="card-back-name" tabindex="-1">
                <div class="cb-outer">
                  <div class="cb-inner">
                    <div class="cb-frame">
                      <header class="cb-header">
                        <span><button type="button" class="cb-list-pill" aria-label="このカードの変更リスト (現在 ${esc(l.name)} にある)">${esc(l.name)}${icon("chevron", 16)}</button></span>
                        <ul>
                          <li><button type="button" class="cb-round-btn" aria-label="カバー">${icon("image", 16)}</button></li>
                          <li><button type="button" class="cb-round-btn" aria-label="ウォッチ">${icon("eye", 16)}</button></li>
                          <li><button type="button" class="cb-round-btn" data-testid="card-back-actions-button" aria-label="アクション">${icon("dots", 16)}</button></li>
                          <li><button type="button" class="cb-round-btn is-plain" data-testid="card-back-close-button" aria-label="ダイアログを閉じる">${icon("close", 16)}</button></li>
                        </ul>
                      </header>
                      <div class="cb-spacer"></div>
                      <div class="cb-body">
                        <main>
                          <section data-testid="card-back-header">
                            <div class="cb-title-icon"><div data-testid="card-done-state"><span class="cb-done-circle" style="display:block"></span></div></div>
                            <hgroup>
                              <h2 id="card-back-name" class="visually-hidden">${esc(card.title)}</h2>
                              <textarea data-testid="card-back-title-input" aria-label="${esc(card.title)}" rows="1" spellcheck="false">${esc(card.title)}</textarea>
                            </hgroup>
                          </section>
                          <div>
                            <div class="cb-quick-actions">
                              <button type="button" class="cb-btn is-outline">${icon("plus", 16)}追加</button>
                              <button type="button" class="cb-btn is-outline">${icon("tag", 16)}ラベル</button>
                              <button type="button" class="cb-btn is-outline">${icon("clock", 16)}日付</button>
                              <button type="button" class="cb-btn is-outline">${icon("checklist", 16)}チェックリスト</button>
                              <button type="button" class="cb-btn is-outline">${icon("people", 16)}メンバー</button>
                            </div>
                            <div class="cb-meta">${meta.join("")}</div>
                            <section class="cb-section" data-testid="card-back-description">
                              <div class="cb-section-icon"><span data-testid="DescriptionIcon">${icon("desc", 20)}</span></div>
                              <hgroup><h3>説明</h3><button type="button" class="cb-btn">編集</button></hgroup>
                              <div class="cb-body-col">${description}</div>
                            </section>
                            ${checklist}
                          </div>
                        </main>
                        <div class="cb-resizer" role="slider" aria-label="ドラッグしてサイズを変更" aria-valuenow="50"></div>
                        <aside>
                          <div data-testid="card-back-panel">
                            <section class="cb-activity">
                              <div class="cb-section-icon">${icon("comment", 20)}</div>
                              <hgroup>
                                <h3>コメントとアクティビティ</h3>
                                <button type="button" class="cb-btn is-outline" data-testid="show-details-button">詳細を非表示</button>
                              </hgroup>
                              <div class="cb-composer-row" data-testid="card-back-comment-composer">
                                ${avatar(ME)}
                                <div class="cb-composer" role="textbox" aria-label="コメントを入力">コメントを入力…</div>
                              </div>
                              <ul data-testid="card-back-actions-list">${d.actions.map(actionItem).join("")}</ul>
                            </section>
                          </div>
                        </aside>
                      </div>
                    </div>
                  </div>
                  <nav class="cb-nav" aria-label="カードの操作">
                    <div role="group">
                      <button type="button" aria-label="Power-Up">${icon("plug", 16)}<span>Power-Up</span></button>
                      <button type="button" aria-label="自動化">${icon("bolt", 16)}<span>自動化</span></button>
                      <span role="separator"></span>
                      <button type="button" data-testid="card-back-activity-button" role="checkbox" aria-checked="true" aria-label="コメントとアクティビティ">${icon("comment", 16)}<span>コメント</span></button>
                    </div>
                  </nav>
                </div>
              </div>
              <div id="dialog-live-region" aria-live="polite"></div>
            </div>
          </div>
        </div>
      </div>`;
  }

  /* ------------------------------------------------------------------
     描画と操作
     ------------------------------------------------------------------ */
  function setPanelOpen(dialog, open) {
    const btn = dialog.querySelector('[data-testid="card-back-activity-button"]');
    btn.setAttribute("aria-checked", open ? "true" : "false");
    dialog.classList.toggle("is-panel-closed", !open);
  }

  function render() {
    const view = document.body.getAttribute("data-view") || "board";
    const root = document.getElementById("trello-root");
    let html = `<div id="chrome-container">${boardView()}</div>`;

    let found = null;
    if (view === "card") {
      const m = /^\/c\/([^/]+)/.exec(location.pathname);
      found = (m && findCard(m[1])) || findCard("Hr8dT0pK");
      html += cardBack(found);
      document.title = `${found.card.title} | ${BOARD.name}`;
    } else {
      document.title = `${BOARD.name} | ボード`;
    }
    root.innerHTML = html;

    // カードをクリックしたらカード詳細へ（Trello と同じ URL の形）
    root.addEventListener("click", (e) => {
      const tile = e.target.closest('[data-testid="trello-card"]');
      if (tile && !e.target.closest("a")) location.href = tile.getAttribute("data-mock-href");
    });

    const dialog = root.querySelector('div[role="dialog"][data-testid="card-back-name"]');
    if (!dialog) return;

    // タイトルの textarea は Trello と同じく中身に合わせて高さが伸びる（幅が変わったら測り直す）
    const title = dialog.querySelector('textarea[data-testid="card-back-title-input"]');
    const fitTitle = () => {
      title.style.height = "auto";
      title.style.height = title.scrollHeight + "px";
    };
    fitTitle();
    new ResizeObserver(fitTitle).observe(title.parentElement);
    // ?comments=closed で、コメント欄を閉じた状態から始める（プレビュー用）
    if (new URLSearchParams(location.search).get("comments") === "closed") setPanelOpen(dialog, false);

    dialog.querySelector('[data-testid="card-back-activity-button"]').addEventListener("click", (e) => {
      const open = e.currentTarget.getAttribute("aria-checked") !== "true";
      setPanelOpen(dialog, open);
    });
    const close = () => {
      location.href = boardUrl();
    };
    dialog.querySelector('[data-testid="card-back-close-button"]').addEventListener("click", close);
    root.querySelector(".card-back-overlay").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) close();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
  }

  render();
})();
