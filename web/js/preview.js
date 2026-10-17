// Board preview as SVG markup, drawn in millimetres (viewBox = page size).
// It mirrors what presentation/board.py places: fills, pictures, drawing slots,
// linework and text. Pure string building, so it can be tested in node.

import {
  FONT_STACKS, LINE_PITCH, drawingPaperSize, gridLines, imagePlacement, innerBox, items,
  principleIcons, texts, titleBand,
} from './model.js';

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const f = (v) => (Math.round(v * 100) / 100).toString();
const CAP = 0.72; // Archicad text height is close to cap height; font-size = height / CAP

function penColour(cfg, name) {
  return cfg.pens[name]?.hex || '#000000';
}

function penWidth(cfg, name) {
  return cfg.pens[name]?.width_mm || 0.1;
}

function textSvg(cfg, t) {
  const lines = t.text.split('\n');
  const fs = t.size / CAP, pitch = t.size * LINE_PITCH;
  const family = FONT_STACKS[cfg.fonts?.[t.font]] || FONT_STACKS['Sans (Helvetica / Arial)'];
  let anchor = 'start', y0;
  if (t.anchor === 'MiddleMiddle') {
    anchor = 'middle';
    y0 = t.y - ((lines.length - 1) * pitch) / 2 + t.size / 2;
  } else if (t.anchor === 'LeftMiddle') {
    y0 = t.y + t.size / 2;
  } else {
    y0 = t.y + t.size;
  }
  const spans = lines.map((line, i) => `<tspan x="${f(t.x)}" y="${f(y0 + i * pitch)}">${esc(line) || ' '}</tspan>`).join('');
  return `<text font-family='${esc(family)}' font-size="${f(fs)}" fill="${penColour(cfg, t.pen)}" text-anchor="${anchor}" data-text="${esc(t.key)}">${spans}</text>`;
}

/**
 * @param cfg board config (normalised)
 * @param opts {pictures: {key: {url, w, h}}, selected, editing, showGrid, showLabels}
 */
export function renderSvg(cfg, opts = {}) {
  const W = cfg.layout.width_mm, H = cfg.layout.height_mm;
  const pics = opts.pictures || {};
  const editing = !!opts.editing;
  const out = [];
  const defs = [];
  out.push(`<rect x="0" y="0" width="${f(W)}" height="${f(H)}" fill="#ffffff"/>`);

  if (editing && opts.showGrid) {
    const { xs, ys } = gridLines(cfg), box = innerBox(cfg);
    const g = [];
    for (let i = 0; i + 1 < xs.length; i += 2) g.push(`<rect x="${f(xs[i])}" y="${f(box.y)}" width="${f(xs[i + 1] - xs[i])}" height="${f(box.h)}"/>`);
    for (let i = 0; i + 1 < ys.length && cfg.configurator.rows > 0; i += 2) g.push(`<rect x="${f(box.x)}" y="${f(ys[i])}" width="${f(box.w)}" height="${f(ys[i + 1] - ys[i])}"/>`);
    out.push(`<g class="grid" fill="#5b8def" fill-opacity="0.05" stroke="#5b8def" stroke-opacity="0.25" stroke-width="0.15">${g.join('')}</g>`);
  }

  // Fills.
  const cream = penColour(cfg, 'cream');
  const band = titleBand(cfg);
  if (band && band.h > 0) out.push(`<rect x="${f(band.x)}" y="${f(band.y)}" width="${f(band.w)}" height="${f(band.h)}" fill="${cream}"/>`);
  for (const p of cfg.placeholders) out.push(`<rect x="${f(p.x)}" y="${f(p.y)}" width="${f(p.w)}" height="${f(p.h)}" fill="${cream}"/>`);

  // Pictures, cropped to their slots (or a circle).
  cfg.images.forEach((img, n) => {
    const id = `clip-img-${n}`;
    const circle = img.shape === 'circle';
    defs.push(circle
      ? `<clipPath id="${id}"><ellipse cx="${f(img.x + img.w / 2)}" cy="${f(img.y + img.h / 2)}" rx="${f(img.w / 2)}" ry="${f(img.h / 2)}"/></clipPath>`
      : `<clipPath id="${id}"><rect x="${f(img.x)}" y="${f(img.y)}" width="${f(img.w)}" height="${f(img.h)}"/></clipPath>`);
    const pic = pics[img.key];
    if (pic) {
      const p = imagePlacement(img, pic, img.crop);
      out.push(`<g clip-path="url(#${id})"><image href="${esc(pic.url)}" x="${f(p.x)}" y="${f(p.y)}" width="${f(p.w)}" height="${f(p.h)}" preserveAspectRatio="none"/></g>`);
    } else {
      out.push(`<g clip-path="url(#${id})"><rect x="${f(img.x)}" y="${f(img.y)}" width="${f(img.w)}" height="${f(img.h)}" fill="#e4e1db"/>`
        + `<path d="M${f(img.x)} ${f(img.y)}L${f(img.x + img.w)} ${f(img.y + img.h)}M${f(img.x + img.w)} ${f(img.y)}L${f(img.x)} ${f(img.y + img.h)}" stroke="#c9c4ba" stroke-width="0.3"/></g>`
        + `<text x="${f(img.x + img.w / 2)}" y="${f(img.y + img.h / 2)}" font-family="sans-serif" font-size="${f(Math.min(6, img.w / 12))}" fill="#8a847a" text-anchor="middle" dominant-baseline="middle">${esc(img.key)} image</text>`);
    }
  });

  // Drawing slots and the paper extent of their clipped view.
  for (const d of cfg.drawings) {
    const s = d.slot, size = drawingPaperSize(d);
    const over = size && (size.w > s.w + 0.5 || size.h > s.h + 0.5);
    out.push(`<rect x="${f(s.x)}" y="${f(s.y)}" width="${f(s.w)}" height="${f(s.h)}" fill="#f4f6f7" stroke="#c4cbcf" stroke-width="0.2" stroke-dasharray="1.2 0.8"/>`);
    if (size) {
      const x = s.x + (s.w - size.w) / 2, y = s.y + (s.h - size.h) / 2;
      out.push(`<rect x="${f(x)}" y="${f(y)}" width="${f(size.w)}" height="${f(size.h)}" fill="none" stroke="${over ? '#d0453a' : '#7c8486'}" stroke-width="${over ? 0.5 : 0.25}"/>`);
    }
    const label = d.fit ? 'fitted to slot' : `1:${d.scale}`;
    const fs = Math.max(2.4, Math.min(4.2, s.w / 24));
    out.push(`<text x="${f(s.x + s.w / 2)}" y="${f(s.y + s.h / 2)}" font-family="sans-serif" font-size="${f(fs)}" fill="${over ? '#d0453a' : '#6b7377'}" text-anchor="middle">`
      + `<tspan x="${f(s.x + s.w / 2)}" dy="0">${esc(d.name.replace(/^PRES-\d+\s*/, ''))}</tspan><tspan x="${f(s.x + s.w / 2)}" dy="${f(fs * 1.3)}">${esc(label)}${over ? ' · too large' : ''}</tspan></text>`);
  }

  // Linework.
  const b = cfg.border;
  out.push(`<rect x="${f(b.inset_x_mm)}" y="${f(b.inset_y_mm)}" width="${f(W - 2 * b.inset_x_mm)}" height="${f(H - 2 * b.inset_y_mm)}" fill="none" stroke="${penColour(cfg, b.pen)}" stroke-width="${f(b.weight_mm)}"/>`);
  const grey = penColour(cfg, 'grey');
  for (const p of cfg.placeholders) {
    out.push(`<path d="M${f(p.x)} ${f(p.y)}L${f(p.x + p.w)} ${f(p.y + p.h)}M${f(p.x)} ${f(p.y + p.h)}L${f(p.x + p.w)} ${f(p.y)}" stroke="${grey}" stroke-width="0.1"/>`);
  }
  const ctx = cfg.images.find((i) => i.key === 'context');
  if (ctx) out.push(`<circle cx="${f(ctx.x + ctx.w / 2)}" cy="${f(ctx.y + ctx.h / 2)}" r="${f(ctx.w / 2)}" fill="none" stroke="${grey}" stroke-width="${f(penWidth(cfg, 'grey'))}"/>`);
  for (const c of principleIcons(cfg)) out.push(`<circle cx="${f(c.cx)}" cy="${f(c.cy)}" r="${f(c.r)}" fill="none" stroke="${penColour(cfg, 'bluegrey')}" stroke-width="${f(penWidth(cfg, 'bluegrey'))}"/>`);

  // Text.
  for (const t of texts(cfg)) out.push(textSvg(cfg, t));

  // Editing overlay: outlines, hit targets and the selection.
  if (editing) {
    const order = { panel: 0, placeholder: 1, image: 2, drawing: 3, caption: 4 };
    const list = items(cfg).sort((a, c) => order[a.kind] - order[c.kind]);
    const ov = [];
    for (const it of list) {
      const r = it.rect, sel = it.id === opts.selected;
      const cls = `hit hit-${it.kind}${sel ? ' sel' : ''}`;
      ov.push(`<rect class="${cls}" data-id="${esc(it.id)}" x="${f(r.x)}" y="${f(r.y)}" width="${f(r.w)}" height="${f(r.h)}"/>`);
      if (it.kind === 'panel' && opts.showLabels) {
        ov.push(`<text class="panel-label" x="${f(r.x + 1)}" y="${f(r.y + 3.2)}">${esc(it.label)}</text>`);
      }
    }
    const sel = list.find((it) => it.id === opts.selected);
    if (sel) {
      const r = sel.rect;
      ov.push(`<rect class="sel-outline" x="${f(r.x)}" y="${f(r.y)}" width="${f(r.w)}" height="${f(r.h)}"/>`);
      if (sel.resizable) {
        const hs = Math.max(2.4, Math.min(W, H) / 160);
        const handles = { nw: [r.x, r.y], n: [r.x + r.w / 2, r.y], ne: [r.x + r.w, r.y], e: [r.x + r.w, r.y + r.h / 2],
          se: [r.x + r.w, r.y + r.h], s: [r.x + r.w / 2, r.y + r.h], sw: [r.x, r.y + r.h], w: [r.x, r.y + r.h / 2] };
        for (const [k, [x, y]] of Object.entries(handles)) {
          ov.push(`<rect class="handle h-${k}" data-handle="${k}" data-id="${esc(sel.id)}" x="${f(x - hs / 2)}" y="${f(y - hs / 2)}" width="${f(hs)}" height="${f(hs)}"/>`);
        }
      }
    }
    out.push(`<g class="overlay">${ov.join('')}</g>`);
  }

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${f(W)} ${f(H)}" width="${f(W)}mm" height="${f(H)}mm" class="board">`
    + `<defs>${defs.join('')}</defs>${out.join('')}</svg>`;
}
