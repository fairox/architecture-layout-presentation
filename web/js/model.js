// Board model: pure functions over a board config (the same JSON build_board reads).
// No DOM here, so everything is tested with `node --test`.
//
// Geometry is in millimetres from the page's upper-left corner, y down, exactly as
// in boards/<board>/board.json. Configurator-only settings (grid, fonts, image
// crops) live in keys the builder ignores: `configurator`, `fonts`, `images[].crop`
// and `images[].shape`.

export const PACKAGE_FORMAT = 'archicad-board';
export const PACKAGE_VERSION = 1;
export const REQUIRED_PENS = ['charcoal', 'grey', 'cream', 'bluegrey'];
export const REQUIRED_PANELS = ['hero', 'info', 'principles', 'explanation'];
export const REQUIRED_IMAGES = ['hero', 'context'];
export const TYPE_KEYS = ['title', 'location', 'heading', 'body', 'caption', 'credit'];
export const GLYPH_WIDTH = 0.68; // same constant as presentation/board.py
export const LINE_PITCH = 1.6; // builder's line advance, as a multiple of text height
export const TOLERANCE_MM = 0.5;
const SAFE_FILE = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}\.(jpe?g|png)$/i;
const GUID = /^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$/;
const HEX = /^#[0-9A-Fa-f]{6}$/;

export const PAGE_PRESETS = [
  { id: 'pres', label: 'Board 600 × 750', w: 600, h: 750 },
  { id: 'a0', label: 'A0 841 × 1189', w: 841, h: 1189 },
  { id: 'a1', label: 'A1 594 × 841', w: 594, h: 841 },
  { id: 'a2', label: 'A2 420 × 594', w: 420, h: 594 },
  { id: 'a3', label: 'A3 297 × 420', w: 297, h: 420 },
];

export const FONT_STACKS = {
  'Serif (Georgia)': 'Georgia, "Times New Roman", serif',
  'Sans (Helvetica / Arial)': '"Helvetica Neue", Helvetica, Arial, sans-serif',
  'Humanist sans (Segoe / Gill)': '"Segoe UI", "Gill Sans", Calibri, sans-serif',
  'Geometric sans (Futura / Century Gothic)': 'Futura, "Century Gothic", "Avenir Next", sans-serif',
  'Mono': 'Consolas, "SF Mono", Menlo, monospace',
};

export const clone = (v) => JSON.parse(JSON.stringify(v));
const num = (v) => typeof v === 'number' && Number.isFinite(v);
export const round = (v, step = 0.05) => Math.round(v / step) * step;
const r2 = (v) => Math.round(v * 100) / 100;

/** Fill in configurator defaults without touching anything the builder reads. */
export function normalise(input) {
  const cfg = clone(input);
  delete cfg.format; delete cfg.version; delete cfg.exportedAt; delete cfg.generator;
  cfg.configurator = Object.assign({ columns: 12, rows: 0, gutter_mm: 6, snap_mm: 0.75, show_grid: true }, cfg.configurator || {});
  cfg.fonts = Object.assign({ title: 'Sans (Helvetica / Arial)', body: 'Sans (Helvetica / Arial)' }, cfg.fonts || {});
  cfg.images = (cfg.images || []).map((img) => {
    const out = { ...img, crop: Object.assign({ fx: 0.5, fy: 0.5, zoom: 1 }, img.crop || {}) };
    if (!out.shape && img.key === 'context') out.shape = 'circle';
    delete out.data;
    return out;
  });
  cfg.drawings = cfg.drawings || [];
  cfg.captions = cfg.captions || [];
  cfg.placeholders = cfg.placeholders || [];
  return cfg;
}

// -- items: everything that can be selected and moved on the board --------------

/** Every selectable rectangle as {id, kind, label, rect, resizable}. */
export function items(cfg) {
  const out = [];
  for (const [name, r] of Object.entries(cfg.panels || {})) out.push({ id: `panel:${name}`, kind: 'panel', label: name, rect: r, resizable: true });
  for (const img of cfg.images) out.push({ id: `image:${img.key}`, kind: 'image', label: img.key, rect: img, resizable: true });
  for (const d of cfg.drawings) out.push({ id: `drawing:${d.key}`, kind: 'drawing', label: d.name, rect: d.slot, resizable: true });
  for (const p of cfg.placeholders) out.push({ id: `placeholder:${p.key}`, kind: 'placeholder', label: p.key, rect: p, resizable: true });
  cfg.captions.forEach((c, i) => {
    const h = cfg.type_mm.caption;
    out.push({ id: `caption:${i}`, kind: 'caption', label: c.text, resizable: false,
      rect: { x: c.x, y: c.y, w: Math.max(8, c.text.length * h * GLYPH_WIDTH), h } });
  });
  return out;
}

/** The live object whose x/y(/w/h) an item id edits. */
export function target(cfg, id) {
  const [kind, key] = splitId(id);
  if (kind === 'panel') return cfg.panels[key];
  if (kind === 'image') return cfg.images.find((i) => i.key === key);
  if (kind === 'drawing') return cfg.drawings.find((d) => d.key === key)?.slot;
  if (kind === 'placeholder') return cfg.placeholders.find((p) => p.key === key);
  if (kind === 'caption') return cfg.captions[Number(key)];
  return undefined;
}

export function splitId(id) {
  const i = id.indexOf(':');
  return [id.slice(0, i), id.slice(i + 1)];
}

export function rectOf(cfg, id) {
  return items(cfg).find((it) => it.id === id)?.rect;
}

/** Items lying fully inside a rectangle (what moves with a panel). */
export function contained(cfg, rect, exceptId) {
  return items(cfg).filter((it) => it.id !== exceptId && it.kind !== 'panel'
    && it.rect.x >= rect.x - TOLERANCE_MM && it.rect.y >= rect.y - TOLERANCE_MM
    && it.rect.x + it.rect.w <= rect.x + rect.w + TOLERANCE_MM && it.rect.y + it.rect.h <= rect.y + rect.h + TOLERANCE_MM);
}

export function moveItem(cfg, id, x, y) {
  const t = target(cfg, id);
  if (!t) return;
  t.x = r2(x); t.y = r2(y);
}

export function resizeItem(cfg, id, rect) {
  const t = target(cfg, id);
  if (!t) return;
  t.x = r2(rect.x); t.y = r2(rect.y);
  if (!id.startsWith('caption:')) { t.w = r2(Math.max(1, rect.w)); t.h = r2(Math.max(1, rect.h)); }
}

// -- grid and snapping -------------------------------------------------------------

export function innerBox(cfg) {
  const b = cfg.border, L = cfg.layout;
  return { x: b.inset_x_mm, y: b.inset_y_mm, w: L.width_mm - 2 * b.inset_x_mm, h: L.height_mm - 2 * b.inset_y_mm };
}

/** Grid column and row edges inside the border: {xs, ys} in mm. */
export function gridLines(cfg) {
  const g = cfg.configurator, box = innerBox(cfg);
  const split = (start, len, n) => {
    if (!n || n < 1) return [start, start + len];
    const cell = (len - g.gutter_mm * (n - 1)) / n;
    const out = [];
    for (let i = 0; i < n; i++) { const a = start + i * (cell + g.gutter_mm); out.push(a, a + cell); }
    return out;
  };
  return { xs: split(box.x, box.w, g.columns), ys: split(box.y, box.h, g.rows) };
}

/** Snap a value to the nearest guide within `reach`, else to the snap step. */
export function snapValue(v, guides, step, reach = 1.5) {
  let best = null;
  for (const gv of guides) if (Math.abs(gv - v) <= reach && (best === null || Math.abs(gv - v) < Math.abs(best - v))) best = gv;
  if (best !== null) return best;
  return step > 0 ? round(v, step) : v;
}

/** Guides for snapping one item: grid lines, border, page centre and the edges of every other item. */
export function guides(cfg, exceptIds = []) {
  const { xs, ys } = gridLines(cfg), box = innerBox(cfg);
  const gx = [...xs, box.x, box.x + box.w, cfg.layout.width_mm / 2];
  const gy = [...ys, box.y, box.y + box.h, cfg.layout.height_mm / 2];
  for (const it of items(cfg)) {
    if (exceptIds.includes(it.id) || it.kind === 'caption') continue;
    gx.push(it.rect.x, it.rect.x + it.rect.w);
    gy.push(it.rect.y, it.rect.y + it.rect.h);
  }
  return { gx, gy };
}

/** Snap a moved rectangle by whichever of its edges is closest to a guide. */
export function snapMove(rect, g, step) {
  const pick = (a, len, list) => {
    const s1 = snapValue(a, list, 0), s2 = snapValue(a + len, list, 0);
    if (s1 !== a && (s2 === a + len || Math.abs(s1 - a) <= Math.abs(s2 - a - len))) return s1;
    if (s2 !== a + len) return s2 - len;
    return step > 0 ? round(a, step) : a;
  };
  return { ...rect, x: pick(rect.x, rect.w, g.gx), y: pick(rect.y, rect.h, g.gy) };
}

// -- page size ----------------------------------------------------------------------

/** Change the page size; with `scaleContent`, stretch every position and size with it. */
export function setPageSize(cfg, w, h, scaleContent) {
  const sx = w / cfg.layout.width_mm, sy = h / cfg.layout.height_mm;
  cfg.layout.width_mm = w; cfg.layout.height_mm = h;
  if (!scaleContent) return cfg;
  const s = (r) => { r.x = r2(r.x * sx); r.y = r2(r.y * sy); if ('w' in r) { r.w = r2(r.w * sx); r.h = r2(r.h * sy); } };
  Object.values(cfg.panels).forEach(s);
  cfg.images.forEach(s);
  cfg.drawings.forEach((d) => s(d.slot));
  cfg.placeholders.forEach(s);
  cfg.captions.forEach(s);
  cfg.border.inset_x_mm = r2(cfg.border.inset_x_mm * sx);
  cfg.border.inset_y_mm = r2(cfg.border.inset_y_mm * sy);
  const t = Math.min(sx, sy);
  for (const k of Object.keys(cfg.type_mm)) cfg.type_mm[k] = r2(cfg.type_mm[k] * t);
  return cfg;
}

// -- drawings and images -------------------------------------------------------------

/** Paper size (mm) of a scaled drawing's model clip, or null when fitted or unclipped. */
export function drawingPaperSize(d) {
  if (d.fit || !Array.isArray(d.model_clip) || !(d.scale > 0)) return null;
  const [x0, y0, x1, y1] = d.model_clip;
  return { w: (x1 - x0) / d.scale * 1000, h: (y1 - y0) / d.scale * 1000 };
}

/**
 * Where a source picture sits so that it covers `slot` (cropped, never stretched).
 * `natural` is the picture's pixel size; `crop` is {fx, fy, zoom} with fx/fy the
 * picture point (0..1) that should sit at the slot's centre. Returns the picture's
 * drawn rectangle in slot units and the visible source window in pixels.
 */
export function imagePlacement(slot, natural, crop = {}) {
  const zoom = Math.max(1, crop.zoom || 1), fx = crop.fx ?? 0.5, fy = crop.fy ?? 0.5;
  const s = Math.max(slot.w / natural.w, slot.h / natural.h) * zoom;
  const dw = natural.w * s, dh = natural.h * s;
  const x = Math.min(slot.x, Math.max(slot.x + slot.w - dw, slot.x + slot.w / 2 - fx * dw));
  const y = Math.min(slot.y, Math.max(slot.y + slot.h - dh, slot.y + slot.h / 2 - fy * dh));
  return { x, y, w: dw, h: dh, source: { x: (slot.x - x) / s, y: (slot.y - y) / s, w: slot.w / s, h: slot.h / s } };
}

// -- text, mirroring presentation/board.py --------------------------------------------

export function wrap(text, widthMm, heightMm) {
  const chars = Math.max(10, Math.floor(widthMm / (heightMm * GLYPH_WIDTH)));
  return text.split('\n').map((p) => {
    if (!p) return '';
    const lines = []; let line = '';
    for (const word of p.split(/\s+/).filter(Boolean)) {
      if (!line) line = word;
      else if ((line + ' ' + word).length <= chars) line += ' ' + word;
      else { lines.push(line); line = word; }
      while (line.length > chars) { lines.push(line.slice(0, chars)); line = line.slice(chars); }
    }
    if (line) lines.push(line);
    return lines.join('\n');
  }).join('\n');
}

/** Every text the builder will place: {key, x, y, text, size, pen, anchor, font}. */
export function texts(cfg) {
  const out = [], size = cfg.type_mm, P = cfg.panels, proj = cfg.project, b = cfg.border;
  const t = (key, x, y, body, kind, pen = 'charcoal', { width, anchor = 'LeftTop', font = 'body' } = {}) => {
    out.push({ key, x, y, text: width ? wrap(body, width, size[kind]) : body, size: size[kind], pen, anchor, font });
  };
  const hero = P.hero, info = P.info, pr = P.principles, ex = P.explanation;
  t('title', hero.x + 10, hero.y + 8, proj.title_lines.join('\n'), 'title', 'charcoal', { font: 'title' });
  t('location', hero.x + 10, hero.y + 8 + size.title * LINE_PITCH * proj.title_lines.length + 2, proj.location, 'location', 'bluegrey');
  t('info', info.x, info.y, proj.info_lines.join('\n'), 'credit');
  const pitch = pr.h / Math.max(1, proj.principles.length);
  proj.principles.forEach((label, n) => {
    const cy = pr.y + pitch * (n + 0.5);
    t(`principle-number-${n + 1}`, pr.x + 5, cy, String(n + 1), 'credit', 'bluegrey', { anchor: 'MiddleMiddle' });
    t(`principle-${n + 1}`, pr.x + 14, cy, label, 'caption', 'charcoal', { anchor: 'LeftMiddle' });
  });
  const colW = (ex.w - 10) / 2;
  proj.explanation.slice(0, 2).forEach((para, n) => t(`explanation-${n + 1}`, ex.x + n * (colW + 10), ex.y, para, 'body', 'charcoal', { width: colW }));
  for (const d of cfg.drawings) t(`caption-${d.key}`, d.slot.x, d.slot.y + d.slot.h + 3, d.caption, 'caption', 'grey');
  cfg.captions.forEach((c, n) => t(`caption-extra-${n + 1}`, c.x, c.y, c.text, 'caption', 'grey'));
  for (const p of cfg.placeholders) {
    t(`placeholder-${p.key}-label`, p.x + p.w / 2, p.y + p.h / 2, p.text, 'caption', 'grey', { anchor: 'MiddleMiddle' });
    t(`caption-${p.key}`, p.x, p.y + p.h + 3, p.caption, 'caption', 'grey');
  }
  t('credit', info.x, cfg.layout.height_mm - b.inset_y_mm - 6, proj.credit, 'credit', 'grey');
  return out;
}

/** Principle icon circles (centre, radius in mm), as the builder draws them. */
export function principleIcons(cfg) {
  const pr = cfg.panels.principles, n = cfg.project.principles.length, pitch = pr.h / Math.max(1, n);
  return Array.from({ length: n }, (_, i) => ({ cx: pr.x + 5, cy: pr.y + pitch * (i + 0.5), r: 4.5 }));
}

/** The cream band above the hero image that carries the title. */
export function titleBand(cfg) {
  const hero = cfg.panels.hero, img = cfg.images.find((i) => i.key === 'hero');
  if (!hero || !img) return null;
  return { x: hero.x, y: hero.y, w: hero.w, h: Math.max(0, img.y - hero.y) };
}

// -- validation, mirroring presentation/package.py --------------------------------------

function rectErrors(where, r, W, H) {
  if (!r || !['x', 'y', 'w', 'h'].every((k) => num(r[k]))) return [`${where} needs numeric x, y, w and h (mm).`];
  const out = [];
  if (r.w <= 0 || r.h <= 0) out.push(`${where} must have a positive width and height.`);
  if (r.x < -TOLERANCE_MM || r.y < -TOLERANCE_MM || r.x + r.w > W + TOLERANCE_MM || r.y + r.h > H + TOLERANCE_MM) out.push(`${where} runs off the ${W} x ${H} mm page.`);
  return out;
}

const inside = (r, [x0, y0, x1, y1]) => r.x >= x0 - TOLERANCE_MM && r.y >= y0 - TOLERANCE_MM && r.x + r.w <= x1 + TOLERANCE_MM && r.y + r.h <= y1 + TOLERANCE_MM;

/** {errors, warnings}; any error means the builder would fail or misplace something. */
export function validate(cfg) {
  const errors = [], warnings = [];
  const lay = cfg?.layout;
  if (!lay) return { errors: ["Missing 'layout'."], warnings };
  for (const k of ['id', 'name', 'subset', 'master']) if (typeof lay[k] !== 'string' || !lay[k].trim()) errors.push(`layout.${k} must be a non-empty text.`);
  if (!(num(lay.width_mm) && num(lay.height_mm) && lay.width_mm > 0 && lay.height_mm > 0)) return { errors: [...errors, 'layout.width_mm and layout.height_mm must be positive numbers.'], warnings };
  const W = lay.width_mm, H = lay.height_mm;
  if (typeof cfg.layer !== 'string' || !cfg.layer.trim()) errors.push("'layer' must name the board layer.");

  const pens = cfg.pens || {};
  const seen = new Map();
  for (const [name, p] of Object.entries(pens)) {
    if (!Number.isInteger(p.index) || p.index < 1 || p.index > 255) errors.push(`Pen '${name}' needs an index from 1 to 255.`);
    else if (seen.has(p.index)) errors.push(`Pens '${seen.get(p.index)}' and '${name}' both use pen ${p.index}.`);
    else seen.set(p.index, name);
    if (typeof p.hex !== 'string' || !HEX.test(p.hex)) errors.push(`Pen '${name}' needs a colour like #303637.`);
    if (!num(p.width_mm) || p.width_mm <= 0 || p.width_mm > 2) errors.push(`Pen '${name}' needs a line weight between 0 and 2 mm.`);
  }
  for (const n of REQUIRED_PENS) if (!(n in pens)) errors.push(`The palette needs a pen named '${n}'.`);
  for (const k of TYPE_KEYS) if (!num(cfg.type_mm?.[k]) || cfg.type_mm[k] <= 0) errors.push(`type_mm.${k} must be a positive text height in mm.`);

  const b = cfg.border || {};
  let inner = [0, 0, W, H];
  if (!['inset_x_mm', 'inset_y_mm', 'weight_mm'].every((k) => num(b[k]) && b[k] >= 0)) errors.push('border needs inset_x_mm, inset_y_mm and weight_mm.');
  else {
    if (!(b.pen in pens)) errors.push(`border.pen '${b.pen}' is not in the palette.`);
    inner = [b.inset_x_mm, b.inset_y_mm, W - b.inset_x_mm, H - b.inset_y_mm];
    if (inner[2] <= inner[0] || inner[3] <= inner[1]) errors.push('The border insets leave no room on the page.');
  }
  const checkRect = (where, r) => {
    const found = rectErrors(where, r, W, H);
    errors.push(...found);
    if (!found.length && !inside(r, inner)) warnings.push(`${where} crosses the page border; the read-back check will flag it.`);
    return !found.length;
  };

  const panels = cfg.panels || {};
  for (const n of REQUIRED_PANELS) if (!(n in panels)) errors.push(`Panel '${n}' is required by the builder.`);
  for (const [n, r] of Object.entries(panels)) errors.push(...rectErrors(`Panel '${n}'`, r, W, H));

  const keys = new Set(), files = new Set();
  (cfg.images || []).forEach((img, i) => {
    const where = `Image '${img.key ?? i}'`;
    if (keys.has(img.key)) errors.push(`${where} appears twice.`);
    keys.add(img.key);
    if (typeof img.file !== 'string' || !SAFE_FILE.test(img.file)) errors.push(`${where} needs a plain .jpg or .png file name (letters, digits, - _ .).`);
    else if (files.has(img.file.toLowerCase())) errors.push(`${where} reuses the file name ${img.file}.`);
    else files.add(img.file.toLowerCase());
    checkRect(where, img);
  });
  for (const k of REQUIRED_IMAGES) if (!keys.has(k)) errors.push(`An image with key '${k}' is required by the builder.`);
  const heroImg = (cfg.images || []).find((i) => i.key === 'hero');
  if (panels.hero && heroImg && heroImg.y < panels.hero.y) errors.push('The hero image starts above the hero panel, so the title band would have a negative height.');

  const dkeys = new Set();
  (cfg.drawings || []).forEach((d, i) => {
    const where = `Drawing '${d.key ?? i}'`;
    if (!d.key || dkeys.has(d.key)) errors.push(`${where} needs a unique key.`);
    dkeys.add(d.key);
    if (typeof d.name !== 'string' || !d.name.trim()) errors.push(`${where} needs a view name.`);
    if (typeof d.source !== 'string' || !GUID.test(d.source)) errors.push(`${where} needs the source view's navigator id (a GUID).`);
    if (!d.fit && !(num(d.scale) && d.scale > 0)) errors.push(`${where} needs a scale (e.g. 500 for 1:500) or fit: true.`);
    let clip = d.model_clip;
    if (clip != null && !(Array.isArray(clip) && clip.length === 4 && clip.every(num) && clip[2] > clip[0] && clip[3] > clip[1])) {
      errors.push(`${where} model_clip must be [x0, y0, x1, y1] in metres with x1 > x0 and y1 > y0.`);
      clip = null;
    }
    if (typeof d.caption !== 'string') errors.push(`${where} needs a caption (may be empty).`);
    if (checkRect(`${where} slot`, d.slot) && clip) {
      const s = drawingPaperSize(d);
      if (s && (s.w > d.slot.w + TOLERANCE_MM || s.h > d.slot.h + TOLERANCE_MM)) {
        warnings.push(`${where} at 1:${d.scale} needs ${s.w.toFixed(0)} x ${s.h.toFixed(0)} mm, more than its ${d.slot.w} x ${d.slot.h} mm slot.`);
      }
    }
  });
  (cfg.captions || []).forEach((c, i) => {
    if (typeof c.text !== 'string' || !num(c.x) || !num(c.y)) errors.push(`Caption ${i + 1} needs text, x and y.`);
  });
  (cfg.placeholders || []).forEach((p, i) => {
    const where = `Placeholder '${p.key ?? i}'`;
    if (!['key', 'text', 'caption'].every((k) => typeof p[k] === 'string')) { errors.push(`${where} needs key, text and caption.`); return; }
    checkRect(where, p);
  });
  const proj = cfg.project;
  if (!proj) errors.push("Missing 'project' text.");
  else {
    for (const k of ['title_lines', 'info_lines', 'principles', 'explanation']) {
      if (!Array.isArray(proj[k]) || !proj[k].every((s) => typeof s === 'string')) errors.push(`project.${k} must be a list of lines.`);
    }
    if (Array.isArray(proj.principles) && !proj.principles.length) errors.push('project.principles needs at least one row.');
    for (const k of ['location', 'credit']) if (typeof proj[k] !== 'string') errors.push(`project.${k} must be text.`);
  }
  return { errors, warnings };
}

// -- export ---------------------------------------------------------------------------

export function fileBase(cfg) {
  return (cfg.layout.id || 'board').replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '') || 'board';
}

/** The board config as it belongs in boards/<board>/board.json (no image data). */
export function toConfig(cfg) {
  const out = clone(cfg);
  for (const img of out.images) delete img.data;
  return out;
}

/** The board file for BuildBoard.py: the config plus each image's cropped data URL. */
export function toPackage(cfg, imageData = {}, generator = '') {
  const out = { format: PACKAGE_FORMAT, version: PACKAGE_VERSION, exportedAt: new Date().toISOString(), generator, ...toConfig(cfg) };
  for (const img of out.images) if (imageData[img.key]) img.data = imageData[img.key];
  return out;
}

/** Pixel size an image is exported at, for a print resolution in dpi. */
export function exportPixels(img, dpi) {
  return { w: Math.max(1, Math.round(img.w / 25.4 * dpi)), h: Math.max(1, Math.round(img.h / 25.4 * dpi)) };
}

/** A key not yet used in `list`, from a base like "plan". */
export function freshKey(list, base) {
  const used = new Set(list.map((x) => x.key));
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) if (!used.has(`${base}-${n}`)) return `${base}-${n}`;
}
