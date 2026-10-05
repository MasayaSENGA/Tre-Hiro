/* トレひろ ストア素材 - 共通の実行部分（render_assets.py が読み取る）
   1. フォントと画像の読み込みを待つ
   2. 撮影画像の目印（.ring[data-box]）を build/geometry.js の矩形に合わせて置く
   3. ページごとの window.layout(H)（矢印・寸法線など）を実行する
   4. 自己検査: 文字の折り返し・はみ出し・切れ、要素の重なり、画像の拡大、
      「Trello」の大きさ、ブランド名の有無
   最後に window.__READY = true、window.__ISSUES / __NOTES / __FOOTNOTES を置く。 */
(function () {
  "use strict";
  const GEOM = window.GEOM || {};
  const DPR = 2;
  const issues = [];
  const SVGNS = "http://www.w3.org/2000/svg";

  function canvasEl() { return document.querySelector(".canvas"); }

  // キャンバス基準の矩形（CSS px）
  function rel(r) {
    const c = canvasEl().getBoundingClientRect();
    return { x: r.left - c.left, y: r.top - c.top, w: r.width, h: r.height,
             r: r.right - c.left, b: r.bottom - c.top,
             cx: r.left - c.left + r.width / 2, cy: r.top - c.top + r.height / 2 };
  }
  function rectOf(el) { return rel(el.getBoundingClientRect()); }

  // 図（figure[data-geom]）の中の名前付き矩形を、キャンバス基準の矩形にする
  function boxRect(fig, name) {
    const g = GEOM[fig.dataset.geom];
    if (!g) throw new Error("no geometry for " + fig.dataset.geom);
    const b = g.boxes[name];
    if (!b) throw new Error("no box " + name + " in " + fig.dataset.geom);
    const ir = fig.querySelector("img").getBoundingClientRect();
    const s = ir.width / g.css_w;
    return rel({ left: ir.left + b[0] * s, top: ir.top + b[1] * s,
                 right: ir.left + b[2] * s, bottom: ir.top + b[3] * s,
                 width: (b[2] - b[0]) * s, height: (b[3] - b[1]) * s });
  }
  // 図の表示倍率（撮影時の CSS px に対する倍率。1 を超えると元の画素より拡大）
  function figScale(fig) {
    const g = GEOM[fig.dataset.geom];
    return fig.querySelector("img").getBoundingClientRect().width / g.css_w;
  }

  function checkFigures() {
    document.querySelectorAll("[data-geom]").forEach((fig) => {
      const g = GEOM[fig.dataset.geom];
      if (!g) { issues.push("missing geometry: " + fig.dataset.geom); return; }
      const img = fig.querySelector("img");
      const r = img.getBoundingClientRect();
      if (Math.abs(r.height / r.width - g.h / g.w) > 0.004) issues.push("aspect ratio changed: " + fig.dataset.geom);
      const s = r.width / g.css_w;
      issues.push(`note: ${fig.dataset.geom} shown at ${(s * 100).toFixed(1)}% of its captured CSS size ` +
                  `(${Math.round(r.width)}x${Math.round(r.height)} CSS px from ${g.w}x${g.h} px)`);
      fig.querySelectorAll(".ring[data-box]").forEach((ring) => {
        const b = g.boxes[ring.dataset.box];
        if (!b) { issues.push("missing box " + ring.dataset.box); return; }
        const pad = parseFloat(ring.dataset.pad || "4");
        const bw = parseFloat(getComputedStyle(ring).borderTopWidth) || 0;
        ring.style.left = (img.offsetLeft + b[0] * s - pad - bw) + "px";
        ring.style.top = (img.offsetTop + b[1] * s - pad - bw) + "px";
        ring.style.width = ((b[2] - b[0]) * s + 2 * (pad + bw)) + "px";
        ring.style.height = ((b[3] - b[1]) * s + 2 * (pad + bw)) + "px";
      });
    });
  }
  // すべての画像: 元の画素 ≥ 表示 CSS px × 2（deviceScaleFactor 2 で拡大にならない）
  function checkResolution() {
    document.querySelectorAll(".canvas img").forEach((img) => {
      const r = img.getBoundingClientRect();
      const src = img.getAttribute("src");
      if (img.naturalWidth + 0.5 < r.width * DPR || img.naturalHeight + 0.5 < r.height * DPR)
        issues.push(`image enlarged: ${src} ${img.naturalWidth}x${img.naturalHeight} px shown at ` +
                    `${r.width.toFixed(1)}x${r.height.toFixed(1)} CSS px (needs x${DPR})`);
    });
  }

  // ---- 矢印・線（SVG） ----
  function wiresSvg() {
    let svg = document.querySelector("svg.wires");
    if (!svg) {
      svg = document.createElementNS(SVGNS, "svg");
      svg.setAttribute("class", "wires");
      const c = canvasEl();
      svg.setAttribute("width", c.clientWidth);
      svg.setAttribute("height", c.clientHeight);
      svg.setAttribute("viewBox", `0 0 ${c.clientWidth} ${c.clientHeight}`);
      c.appendChild(svg);
    }
    return svg;
  }
  function path(d, opts = {}) {
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", d);
    p.setAttribute("fill", "none");
    p.setAttribute("stroke", opts.color || "#f59e0b");
    p.setAttribute("stroke-width", opts.width || 3);
    p.setAttribute("stroke-linecap", opts.cap || "round");
    p.setAttribute("stroke-linejoin", "round");
    if (opts.dash) p.setAttribute("stroke-dasharray", opts.dash);
    wiresSvg().appendChild(p);
    return p;
  }
  function dot(x, y, r = 4.5, color = "#f59e0b") {
    const c = document.createElementNS(SVGNS, "circle");
    c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("r", r);
    c.setAttribute("fill", color);
    c.setAttribute("stroke", "#fff"); c.setAttribute("stroke-width", 2);
    wiresSvg().appendChild(c);
  }
  function head(x, y, ang, opts = {}) {
    const L = opts.size || 14, W = (opts.size || 14) * 0.62;
    const bx = x - L * Math.cos(ang), by = y - L * Math.sin(ang);
    const nx = -Math.sin(ang), ny = Math.cos(ang);
    const p = document.createElementNS(SVGNS, "path");
    p.setAttribute("d", `M ${x} ${y} L ${bx + nx * W} ${by + ny * W} L ${bx - nx * W} ${by - ny * W} Z`);
    p.setAttribute("fill", opts.color || "#f59e0b");
    p.setAttribute("stroke", opts.color || "#f59e0b");
    p.setAttribute("stroke-width", 2);
    p.setAttribute("stroke-linejoin", "round");
    wiresSvg().appendChild(p);
  }
  function endAngle(pts) {
    const p1 = pts[pts.length - 1];
    for (let i = pts.length - 2; i >= 0; i--) {
      const q = pts[i];
      if (Math.hypot(p1.x - q.x, p1.y - q.y) > 1e-6) return Math.atan2(p1.y - q.y, p1.x - q.x);
    }
    throw new Error("arrow has zero length");
  }
  function lineArrow(p0, p1, opts = {}) {
    const inset = (opts.size || 14) * 0.7;
    const ang = endAngle([p0, p1]);
    const ex = p1.x - inset * Math.cos(ang), ey = p1.y - inset * Math.sin(ang);
    path(`M ${p0.x} ${p0.y} L ${ex} ${ey}`, opts);
    head(p1.x, p1.y, ang, opts);
    return { ang, end: { x: ex, y: ey } };
  }
  function curveArrow(p0, c0, c1, p1, opts = {}) {
    const inset = (opts.size || 14) * 0.7;
    const ang = endAngle([p0, c0, c1, p1]);
    const ex = p1.x - inset * Math.cos(ang), ey = p1.y - inset * Math.sin(ang);
    path(`M ${p0.x} ${p0.y} C ${c0.x} ${c0.y}, ${c1.x} ${c1.y}, ${ex} ${ey}`, opts);
    head(p1.x, p1.y, ang, opts);
    return { ang, end: { x: ex, y: ey } };
  }
  // 寸法線（両端に短い縦線）: x0〜x1 を y の高さに
  function dimLine(x0, x1, y, opts = {}) {
    const t = opts.tick || 7;
    path(`M ${x0} ${y - t} L ${x0} ${y + t} M ${x1} ${y - t} L ${x1} ${y + t} M ${x0} ${y} L ${x1} ${y}`,
         Object.assign({ cap: "butt" }, opts));
  }
  function deg(rad) { return rad * 180 / Math.PI; }
  function overlaps(a, b, tol = 0.5) {
    return Math.min(a.r, b.r) - Math.max(a.x, b.x) > tol && Math.min(a.b, b.b) - Math.max(a.y, b.y) > tol;
  }

  // ---- 自己検査 ----
  function textRects(node) {
    const range = document.createRange();
    range.selectNodeContents(node);
    return [...range.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5);
  }
  function checkText() {
    const c = canvasEl();
    const cr = c.getBoundingClientRect();
    const walker = document.createTreeWalker(c, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      const t = n.textContent.trim();
      if (!t) continue;
      const el = n.parentElement;
      if (el.closest("svg")) continue;
      const rects = textRects(n);
      if (!rects.length) { issues.push("text not rendered: " + t); continue; }
      const tops = new Set(rects.map((r) => Math.round(r.top / 4)));
      if (tops.size > 1) issues.push("text wraps onto several lines: " + t);
      for (const r of rects) {
        if (r.left < cr.left - 0.5 || r.right > cr.right + 0.5 || r.top < cr.top - 0.5 || r.bottom > cr.bottom + 0.5) {
          issues.push("text outside canvas: " + t);
          break;
        }
      }
      const col = el.closest("[data-col]");
      if (col) {
        const colR = col.getBoundingClientRect();
        const lim = colR.left + parseFloat(col.dataset.col);
        for (const r of rects) {
          if (r.right > lim + 0.5) { issues.push(`text wider than column (${Math.round(r.right - colR.left)} > ${col.dataset.col}): ${t}`); break; }
        }
      }
      // overflow:hidden の祖先で切れていない
      let a = el;
      while (a && a !== c) {
        const cs = getComputedStyle(a);
        if (cs.overflow === "hidden" || cs.overflowX === "hidden" || cs.overflowY === "hidden") {
          const ar = a.getBoundingClientRect();
          for (const r of rects) {
            if (r.right > ar.right + 0.5 || r.left < ar.left - 0.5 || r.bottom > ar.bottom + 0.5 || r.top < ar.top - 0.5) {
              issues.push("text clipped by container: " + t);
              break;
            }
          }
        }
        a = a.parentElement;
      }
      // 自分の箱からはみ出していない（white-space: nowrap の行が箱より長い）
      if (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).display !== "inline")
        issues.push(`text overflows its box (${el.scrollWidth} > ${el.clientWidth}): ${t}`);
    }
  }
  function checkBlocks() {
    const blocks = [...document.querySelectorAll("[data-block]")];
    const rs = blocks.map((b) => [b, rectOf(b)]);
    const W = canvasEl().clientWidth, Hh = canvasEl().clientHeight;
    for (const [b, r] of rs) {
      if (r.x < -0.5 || r.y < -0.5 || r.r > W + 0.5 || r.b > Hh + 0.5)
        issues.push("block outside canvas: " + b.dataset.block);
    }
    for (let i = 0; i < rs.length; i++) {
      for (let j = i + 1; j < rs.length; j++) {
        const [a, ra] = rs[i], [b, rb] = rs[j];
        const ok = (a.dataset.overlapOk || "").split(/\s+/).includes(b.dataset.block) ||
                   (b.dataset.overlapOk || "").split(/\s+/).includes(a.dataset.block);
        if (!ok && overlaps(ra, rb)) issues.push(`blocks overlap: ${a.dataset.block} / ${b.dataset.block}`);
      }
    }
  }
  // 「Trello」はブランド名より大きくしない。大見出しには入れない
  function checkTrello() {
    const brand = document.querySelector(".brand-name, .name");
    if (!brand) { issues.push("brand name (トレひろ) missing"); return; }
    if (brand.textContent.trim() !== "トレひろ") issues.push("brand name is not トレひろ: " + brand.textContent);
    const bs = parseFloat(getComputedStyle(brand).fontSize);
    const walker = document.createTreeWalker(canvasEl(), NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if (!/trello/i.test(n.textContent)) continue;
      const el = n.parentElement;
      if (el.closest(".headline, .name")) issues.push("Trello in a headline: " + n.textContent.trim());
      const fs = parseFloat(getComputedStyle(el).fontSize);
      if (fs > bs + 0.01) issues.push(`Trello (${fs}px) larger than the brand name (${bs}px): ${n.textContent.trim()}`);
    }
  }
  function checkFonts() {
    const faces = [...document.fonts].filter((f) => f.family.replace(/"/g, "") === "TH Sans");
    if (!faces.length) issues.push("no TH Sans face declared (build/font.css)");
    faces.forEach((f) => { if (f.status === "error") issues.push("font failed: TH Sans " + f.weight); });
    if (!faces.some((f) => f.status === "loaded")) issues.push("TH Sans not loaded");
  }
  function footnotes() {
    return [...document.querySelectorAll(".footnote, .footnote2")].map((el) => {
      const r = rectOf(el);
      const m = getComputedStyle(el).color.match(/[\d.]+/g).map(Number);
      if (m.length > 3 && m[3] < 1) issues.push("footnote colour must be opaque");
      return { sel: "." + el.className.split(/\s+/)[0], rect: [r.x, r.y, r.r, r.b], color: m.slice(0, 3) };
    });
  }

  window.H = { rectOf, boxRect, figScale, path, dot, head, lineArrow, curveArrow, dimLine, deg, overlaps, issues };

  async function run() {
    try {
      for (const w of [400, 500, 600, 700, 800]) {
        try { await document.fonts.load(`${w} 20px "TH Sans"`, "トレひろ Trello 0"); }
        catch (e) { issues.push(`font weight ${w} failed: ${e}`); }
      }
      await document.fonts.ready;
      const imgs = [...document.images];
      await Promise.all(imgs.map((i) => (i.complete ? Promise.resolve() : new Promise((r) => { i.onload = i.onerror = r; }))));
      await Promise.all(imgs.map((i) => (i.decode ? i.decode().catch(() => {}) : null)));
      imgs.forEach((i) => { if (!i.naturalWidth) issues.push("image failed: " + i.getAttribute("src")); });
      checkFonts();
      if (typeof window.layout === "function") await window.layout(window.H);
      checkFigures();                                   // 大きさが決まってから倍率を測り、目印を置く
      if (typeof window.afterLayout === "function") await window.afterLayout(window.H);
      checkResolution();
      checkText();
      checkBlocks();
      checkTrello();
      window.__FOOTNOTES = footnotes();
    } catch (e) {
      issues.push("exception: " + (e && e.stack || e));
    }
    window.__ISSUES = issues.filter((m) => !m.startsWith("note:"));
    window.__NOTES = issues.filter((m) => m.startsWith("note:"));
    window.__READY = true;
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run);
  else run();
})();
