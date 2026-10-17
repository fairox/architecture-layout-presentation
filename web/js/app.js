// Board Configurator: edit a presentation board config, preview it live, and export
// the board file that web/archicad/BuildBoard.py builds in Archicad through Tapir.
// The page never talks to Archicad; everything stays in this browser.

import {
  FONT_STACKS, PAGE_PRESETS, clone, contained, fileBase, freshKey, guides, normalise, rectOf, resizeItem,
  setPageSize, snapMove, snapValue, splitId, target, toConfig, toPackage, validate,
} from './model.js';
import { renderSvg } from './preview.js';
import { cropToDataUrl, deletePicture, loadPicture, pictureFromDataUrl, restorePictures, savePicture } from './images.js';

const GENERATOR = 'board-configurator/1';
const STORE_KEY = 'board-configurator:cfg:v1';
const UI_KEY = 'board-configurator:ui:v1';
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const state = {
  cfg: null,
  pictures: {}, // image key -> {blob, url, w, h, name, el}
  selected: null,
  tab: 'page',
  history: [],
  future: [],
  zoom: 0, // 0 = fit
  showGrid: true,
  showLabels: true,
  editing: true,
  moveContents: true,
  dpi: 150,
  presets: [],
  lastEdit: { key: '', at: 0 },
};

// -- storage (best effort; the app works without it) ---------------------------------

const store = {
  get(key) { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } },
  set(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* quota or blocked */ } },
};

function saveSoon() {
  clearTimeout(saveSoon.t);
  saveSoon.t = setTimeout(() => store.set(STORE_KEY, state.cfg), 250);
}

function saveUi() {
  store.set(UI_KEY, { tab: state.tab, showGrid: state.showGrid, showLabels: state.showLabels, dpi: state.dpi, moveContents: state.moveContents });
}

// -- editing and history --------------------------------------------------------------

/** Change the config through `fn`; consecutive edits of the same field share one undo step. */
function edit(fn, { key = '', forms = false } = {}) {
  const before = JSON.stringify(state.cfg);
  fn(state.cfg);
  if (JSON.stringify(state.cfg) === before) return;
  const now = Date.now();
  if (!(key && key === state.lastEdit.key && now - state.lastEdit.at < 1200)) {
    state.history.push(before);
    if (state.history.length > 150) state.history.shift();
  }
  state.lastEdit = { key, at: now };
  state.future = [];
  afterChange(forms);
}

function afterChange(forms) {
  saveSoon();
  renderBoard();
  renderStatus();
  renderInspector();
  if (forms) renderTab();
  else refreshTabHints();
}

function undo() {
  if (!state.history.length) return;
  state.future.push(JSON.stringify(state.cfg));
  state.cfg = JSON.parse(state.history.pop());
  state.lastEdit = { key: '', at: 0 };
  if (state.selected && !rectOf(state.cfg, state.selected)) state.selected = null;
  afterChange(true);
}

function redo() {
  if (!state.future.length) return;
  state.history.push(JSON.stringify(state.cfg));
  state.cfg = JSON.parse(state.future.pop());
  afterChange(true);
}

function loadConfig(cfg, { keepHistory = false } = {}) {
  if (keepHistory && state.cfg) state.history.push(JSON.stringify(state.cfg));
  else { state.history = []; state.future = []; }
  state.cfg = normalise(cfg);
  state.selected = null;
  afterChange(true);
}

// -- paths for generic form binding -------------------------------------------------

function getPath(obj, path) {
  return path.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);
}

function setPath(obj, path, value) {
  const keys = path.split('.');
  const last = keys.pop();
  const parent = keys.reduce((o, k) => o[k], obj);
  parent[last] = value;
}

function readInput(el) {
  const type = el.dataset.type || 'text';
  if (type === 'number') {
    const v = parseFloat(el.value);
    return Number.isFinite(v) ? v : null;
  }
  if (type === 'int') {
    const v = parseInt(el.value, 10);
    return Number.isFinite(v) ? v : null;
  }
  if (type === 'bool') return el.checked;
  if (type === 'lines') {
    const lines = el.value.replace(/\r/g, '').split('\n');
    while (lines.length && lines[lines.length - 1] === '') lines.pop();
    return lines;
  }
  if (type === 'csv-numbers') {
    const parts = el.value.split(/[,\s]+/).filter(Boolean).map(Number);
    return parts.length === 4 && parts.every(Number.isFinite) ? parts : (el.value.trim() ? undefined : null);
  }
  return el.value;
}

function bindValue(path, type = 'text') {
  const v = getPath(state.cfg, path);
  if (type === 'lines') return esc((v || []).join('\n'));
  if (type === 'csv-numbers') return esc(Array.isArray(v) ? v.join(', ') : '');
  return esc(v ?? '');
}

const field = (label, path, { type = 'text', step, min, placeholder, title } = {}) => {
  const inputType = type === 'number' || type === 'int' ? 'number' : 'text';
  return `<div class="row"><label for="f-${esc(path)}">${esc(label)}</label><input id="f-${esc(path)}" type="${inputType}" data-bind="${esc(path)}" data-type="${type}"`
    + `${step ? ` step="${step}"` : ''}${min !== undefined ? ` min="${min}"` : ''}${placeholder ? ` placeholder="${esc(placeholder)}"` : ''}${title ? ` title="${esc(title)}"` : ''} value="${bindValue(path, type)}"></div>`;
};

const area = (label, path, rows = 4) => `<div class="row wide"><label for="f-${esc(path)}">${esc(label)}</label><textarea id="f-${esc(path)}" rows="${rows}" data-bind="${esc(path)}" data-type="lines">${bindValue(path, 'lines')}</textarea></div>`;

// -- tabs ---------------------------------------------------------------------------------

function renderTab() {
  document.querySelectorAll('.tabs button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === state.tab)));
  const body = $('tabBody');
  const html = { page: tabPage, style: tabStyle, content: tabContent, sources: tabSources, build: tabBuild }[state.tab]();
  body.innerHTML = html;
  $('boardTitle').textContent = `${state.cfg.layout.id} · ${state.cfg.layout.width_mm} × ${state.cfg.layout.height_mm} mm`;
  $('undoBtn').disabled = !state.history.length;
  $('redoBtn').disabled = !state.future.length;
}

function refreshTabHints() {
  $('undoBtn').disabled = !state.history.length;
  $('redoBtn').disabled = !state.future.length;
  $('boardTitle').textContent = `${state.cfg.layout.id} · ${state.cfg.layout.width_mm} × ${state.cfg.layout.height_mm} mm`;
  const checks = $('checksList');
  if (checks) checks.innerHTML = checksHtml();
}

function tabPage() {
  const L = state.cfg.layout;
  const preset = PAGE_PRESETS.find((p) => (p.w === L.width_mm && p.h === L.height_mm) || (p.h === L.width_mm && p.w === L.height_mm));
  return `
  <fieldset><legend>Layout</legend>
    ${field('Layout ID', 'layout.id', { title: 'Custom layout number; the builder finds the layout by it' })}
    ${field('Layout name', 'layout.name')}
    ${field('Subset', 'layout.subset')}
    ${field('Master', 'layout.master')}
    ${field('Board layer', 'layer')}
    ${field('Publisher set', 'layout.publisher_set')}
  </fieldset>
  <fieldset><legend>Page size</legend>
    <div class="row"><label for="pagePreset">Preset</label><select id="pagePreset" data-action="page-preset">
      <option value="">Custom</option>${PAGE_PRESETS.map((p) => `<option value="${p.id}" ${preset?.id === p.id ? 'selected' : ''}>${esc(p.label)}</option>`).join('')}</select></div>
    <div class="row"><label>Width × height</label><div class="pair">
      <input type="number" id="pageW" min="50" step="1" value="${L.width_mm}" aria-label="Width (mm)">
      <input type="number" id="pageH" min="50" step="1" value="${L.height_mm}" aria-label="Height (mm)"></div></div>
    <div class="inline">
      <button type="button" data-action="page-apply">Apply size</button>
      <button type="button" data-action="page-rotate">Swap portrait / landscape</button>
    </div>
    <label class="check"><input type="checkbox" id="scaleContent" checked> Scale the layout with the page</label>
  </fieldset>
  <fieldset><legend>Border</legend>
    <div class="row"><label>Inset x / y (mm)</label><div class="pair">
      <input type="number" step="0.25" data-bind="border.inset_x_mm" data-type="number" value="${state.cfg.border.inset_x_mm}" aria-label="Inset x">
      <input type="number" step="0.25" data-bind="border.inset_y_mm" data-type="number" value="${state.cfg.border.inset_y_mm}" aria-label="Inset y"></div></div>
    ${field('Line weight (mm)', 'border.weight_mm', { type: 'number', step: 0.01 })}
    <div class="row"><label for="borderPen">Pen</label><select id="borderPen" data-bind="border.pen">${Object.keys(state.cfg.pens).map((p) => `<option ${p === state.cfg.border.pen ? 'selected' : ''}>${esc(p)}</option>`).join('')}</select></div>
  </fieldset>
  <fieldset><legend>Panel grid</legend>
    <p class="muted" style="margin:0">Guides inside the border. Items snap to grid lines, to each other and to the snap step.</p>
    <div class="row"><label>Columns / rows</label><div class="pair">
      <input type="number" min="0" max="48" step="1" data-bind="configurator.columns" data-type="int" value="${state.cfg.configurator.columns}" aria-label="Columns">
      <input type="number" min="0" max="48" step="1" data-bind="configurator.rows" data-type="int" value="${state.cfg.configurator.rows}" aria-label="Rows"></div></div>
    ${field('Gutter (mm)', 'configurator.gutter_mm', { type: 'number', step: 0.25, min: 0 })}
    ${field('Snap step (mm)', 'configurator.snap_mm', { type: 'number', step: 0.05, min: 0 })}
  </fieldset>`;
}

function tabStyle() {
  const pens = Object.entries(state.cfg.pens);
  return `
  <fieldset><legend>Palette</legend>
    <p class="muted" style="margin:0">Written into otherwise unused pens of the pen table below. Index is the pen number in Archicad.</p>
    <div class="pen muted"><span></span><span>Name</span><span>Hex</span><span>Pen</span><span>mm</span></div>
    ${pens.map(([name, p]) => `<div class="pen">
      <input type="color" data-bind="pens.${esc(name)}.hex" value="${esc(p.hex)}" aria-label="${esc(name)} colour">
      <span>${esc(name)}</span>
      <input type="text" data-bind="pens.${esc(name)}.hex" value="${esc(p.hex)}" aria-label="${esc(name)} hex" maxlength="7">
      <input type="number" min="1" max="255" step="1" data-bind="pens.${esc(name)}.index" data-type="int" value="${p.index}" aria-label="${esc(name)} pen index">
      <input type="number" min="0.01" max="2" step="0.01" data-bind="pens.${esc(name)}.width_mm" data-type="number" value="${p.width_mm}" aria-label="${esc(name)} weight"></div>`).join('')}
    ${field('Pen table', 'pen_table')}
    ${field('Solid fill', 'solid_fill')}
  </fieldset>
  <fieldset><legend>Type sizes (mm)</legend>
    ${Object.keys(state.cfg.type_mm).map((k) => field(k[0].toUpperCase() + k.slice(1), `type_mm.${k}`, { type: 'number', step: 0.05, min: 0.5 })).join('')}
  </fieldset>
  <fieldset><legend>Fonts</legend>
    <p class="muted" style="margin:0">Shown in the preview. Tapir cannot set fonts, so the build uses the layout's default font; the script reminds you of this choice.</p>
    ${['title', 'body'].map((k) => `<div class="row"><label for="font-${k}">${k === 'title' ? 'Title' : 'Body and captions'}</label><select id="font-${k}" data-bind="fonts.${k}">
      ${Object.keys(FONT_STACKS).map((f) => `<option ${state.cfg.fonts[k] === f ? 'selected' : ''}>${esc(f)}</option>`).join('')}</select></div>`).join('')}
  </fieldset>`;
}

function tabContent() {
  const c = state.cfg;
  return `
  <fieldset><legend>Title</legend>
    ${area('Title lines', 'project.title_lines', 2)}
    ${field('Location', 'project.location')}
  </fieldset>
  <fieldset><legend>Panels</legend>
    ${area('Project information', 'project.info_lines', 6)}
    ${area('Design principles (one row each)', 'project.principles', 5)}
    <div class="row wide"><label for="ex0">Explanation, left column</label><textarea id="ex0" rows="4" data-bind="project.explanation.0">${esc(c.project.explanation[0] || '')}</textarea></div>
    <div class="row wide"><label for="ex1">Explanation, right column</label><textarea id="ex1" rows="4" data-bind="project.explanation.1">${esc(c.project.explanation[1] || '')}</textarea></div>
    ${field('Credit line', 'project.credit')}
  </fieldset>
  <fieldset><legend>Captions</legend>
    ${c.captions.map((cap, i) => `<div class="card ${state.selected === `caption:${i}` ? 'selected' : ''}">
      <div class="card-head"><input type="text" data-bind="captions.${i}.text" value="${esc(cap.text)}" aria-label="Caption text" style="flex:1">
      <button type="button" data-action="select" data-id="caption:${i}" title="Select on the board">◎</button>
      <button type="button" class="danger" data-action="remove-caption" data-index="${i}" aria-label="Remove caption">✕</button></div></div>`).join('')}
    <button type="button" data-action="add-caption">Add caption</button>
  </fieldset>
  <fieldset><legend>Placeholders</legend>
    ${c.placeholders.map((p, i) => `<div class="card ${state.selected === `placeholder:${p.key}` ? 'selected' : ''}">
      <div class="card-head"><strong>${esc(p.key)}</strong><span>
        <button type="button" data-action="select" data-id="placeholder:${esc(p.key)}">◎</button>
        <button type="button" class="danger" data-action="remove-placeholder" data-index="${i}" aria-label="Remove placeholder">✕</button></span></div>
      <textarea rows="3" data-bind="placeholders.${i}.text" data-type="text" aria-label="Placeholder text">${esc(p.text)}</textarea>
      <input type="text" data-bind="placeholders.${i}.caption" value="${esc(p.caption)}" aria-label="Placeholder caption"></div>`).join('')}
    <button type="button" data-action="add-placeholder">Add placeholder</button>
  </fieldset>`;
}

function imageCard(img, i) {
  const pic = state.pictures[img.key];
  const required = img.key === 'hero' || img.key === 'context';
  return `<div class="card ${state.selected === `image:${img.key}` ? 'selected' : ''}">
    <div class="card-head"><strong>${esc(img.key)}</strong><span>
      <button type="button" data-action="select" data-id="image:${esc(img.key)}">◎</button>
      ${required ? '' : `<button type="button" class="danger" data-action="remove-image" data-index="${i}" aria-label="Remove image">✕</button>`}</span></div>
    ${pic ? `<img class="thumb" src="${esc(pic.url)}" alt="${esc(img.key)} source">` : ''}
    <label class="drop" data-drop="${esc(img.key)}">${pic ? `${esc(pic.name)} · ${pic.w} × ${pic.h} px — replace` : 'Drop a render or photo, or click to choose'}
      <input type="file" accept="image/jpeg,image/png,image/webp" data-picture="${esc(img.key)}" hidden></label>
    ${pic ? `<div class="inline"><button type="button" data-action="clear-picture" data-key="${esc(img.key)}">Remove picture</button></div>` : ''}
    <div class="row"><label>File in Archicad</label><input type="text" data-bind="images.${i}.file" value="${esc(img.file)}"></div>
    <div class="row"><label>Source note</label><input type="text" data-bind="images.${i}.source" value="${esc(img.source || '')}"></div>
    <div class="row"><label>Shape</label><select data-bind="images.${i}.shape"><option value="rect" ${img.shape !== 'circle' ? 'selected' : ''}>Rectangle</option><option value="circle" ${img.shape === 'circle' ? 'selected' : ''}>Circle</option></select></div>
    <div class="row"><label>Focus x / y</label><div class="pair">
      <input type="range" min="0" max="1" step="0.01" data-bind="images.${i}.crop.fx" data-type="number" value="${img.crop.fx}" aria-label="Horizontal focus">
      <input type="range" min="0" max="1" step="0.01" data-bind="images.${i}.crop.fy" data-type="number" value="${img.crop.fy}" aria-label="Vertical focus"></div></div>
    <div class="row"><label>Zoom</label><input type="range" min="1" max="4" step="0.01" data-bind="images.${i}.crop.zoom" data-type="number" value="${img.crop.zoom}" aria-label="Zoom"></div>
  </div>`;
}

function drawingCard(d, i) {
  return `<div class="card ${state.selected === `drawing:${d.key}` ? 'selected' : ''}">
    <div class="card-head"><strong>${esc(d.key)}</strong><span>
      <button type="button" data-action="select" data-id="drawing:${esc(d.key)}">◎</button>
      <button type="button" class="danger" data-action="remove-drawing" data-index="${i}" aria-label="Remove drawing">✕</button></span></div>
    <div class="row"><label>Board view name</label><input type="text" data-bind="drawings.${i}.name" value="${esc(d.name)}"></div>
    <div class="row"><label>Source view id</label><input type="text" data-bind="drawings.${i}.source" value="${esc(d.source)}" placeholder="View Map navigator GUID" spellcheck="false"></div>
    <div class="row"><label>Scale 1:</label><div class="inline">
      <input type="number" min="1" step="1" data-bind="drawings.${i}.scale" data-type="number" value="${d.scale ?? ''}" ${d.fit ? 'disabled' : ''} style="width:90px">
      <label class="check"><input type="checkbox" data-bind="drawings.${i}.fit" data-type="bool" ${d.fit ? 'checked' : ''}> Fit to slot</label></div></div>
    <div class="row"><label title="Model area to show, metres: x0, y0, x1, y1">Model clip (m)</label><input type="text" data-bind="drawings.${i}.model_clip" data-type="csv-numbers" value="${bindValue(`drawings.${i}.model_clip`, 'csv-numbers')}" placeholder="x0, y0, x1, y1 (optional)"></div>
    <div class="row"><label>Caption</label><input type="text" data-bind="drawings.${i}.caption" value="${esc(d.caption)}"></div>
  </div>`;
}

function tabSources() {
  const c = state.cfg, pv = c.presentation_views;
  return `
  <fieldset><legend>Pictures</legend>
    <p class="muted" style="margin:0">Renders and photos are cropped to their slots in this browser (never stretched) and travel inside the board file.</p>
    ${c.images.map(imageCard).join('')}
    <button type="button" data-action="add-image">Add picture slot</button>
  </fieldset>
  <fieldset><legend>Drawings</legend>
    <p class="muted" style="margin:0">Linked views from the project's View Map, placed at a true scale and clipped to the model area. The grey frame in each slot is that area on paper; red means it is larger than the slot.</p>
    ${c.drawings.map(drawingCard).join('')}
    <button type="button" data-action="add-drawing">Add drawing</button>
  </fieldset>
  ${pv ? `<fieldset><legend>Board views</legend>
    <p class="muted" style="margin:0">Copies of the source views in their own View Map folder, with a quieter layer combination. The project's views are not changed.</p>
    ${field('View Map folder', 'presentation_views.folder')}
    ${field('Layer combination', 'presentation_views.layer_combination')}
    ${field('Pen set', 'presentation_views.pen_set')}
    ${area('Hide layers starting with', 'presentation_views.hide_layer_prefixes', 6)}
  </fieldset>` : ''}`;
}

function checksHtml() {
  const { errors, warnings } = validate(state.cfg);
  const missing = state.cfg.images.filter((i) => !state.pictures[i.key]).map((i) => i.key);
  const rows = [
    ...errors.map((e) => `<li class="err">${esc(e)}</li>`),
    ...warnings.map((w) => `<li class="warn">${esc(w)}</li>`),
    ...(missing.length ? [`<li class="warn">No picture loaded for ${esc(missing.join(', '))}. The script then looks for ${esc(state.cfg.images.filter((i) => missing.includes(i.key)).map((i) => i.file).join(', '))} in the --assets folder.</li>`] : []),
  ];
  return rows.length ? `<ul class="list">${rows.join('')}</ul>` : '<p style="margin:0;color:var(--ok)">Everything checks out.</p>';
}

function tabBuild() {
  const name = `${fileBase(state.cfg)}.board.json`;
  const win = `python BuildBoard.py "%USERPROFILE%\\Downloads\\${name}" --publish`;
  const mac = `python3 BuildBoard.py ~/Downloads/${name} --publish`;
  return `
  <fieldset><legend>Checks</legend><div id="checksList">${checksHtml()}</div></fieldset>
  <fieldset><legend>Export</legend>
    <div class="row"><label for="dpi">Picture resolution</label><select id="dpi">${[100, 150, 200, 300].map((d) => `<option value="${d}" ${d === state.dpi ? 'selected' : ''}>${d} dpi</option>`).join('')}</select></div>
    <button type="button" class="primary" data-action="export-package">Download board file (${esc(name)})</button>
    <button type="button" data-action="export-script">Download Tapir script (BuildBoard.py)</button>
    <button type="button" data-action="export-config">Download config only (board.json)</button>
    <button type="button" data-action="export-png">Download preview image (PNG)</button>
  </fieldset>
  <fieldset><legend>Build in Archicad</legend>
    <ol class="steps">
      <li>Open the project in Archicad with the Tapir add-on.</li>
      <li>Download the board file and <code>BuildBoard.py</code> (Python 3.9+, standard library only).</li>
      <li>Run it on that computer. It validates the file, unpacks the pictures, compiles the picture object with Archicad's LP_XMLConverter, then builds or rebuilds the layout and checks every placement.</li>
    </ol>
    <div class="cmd"><code id="cmdWin">${esc(win)}</code><button type="button" data-action="copy" data-target="cmdWin">Copy</button></div>
    <div class="cmd"><code id="cmdMac">${esc(mac)}</code><button type="button" data-action="copy" data-target="cmdMac">Copy</button></div>
    <p class="muted" style="margin:0">From the Tapir palette: save <code>BuildBoard.py</code> in the palette's script folder and run it there; it opens a file picker. Add <code>--check</code> to validate without Archicad. Work files and the manifest that lets a rerun replace only its own elements go to <code>Documents/Archicad Boards/${esc(state.cfg.layout.id)}</code>.</p>
    <p class="muted" style="margin:0">Known limits: Tapir cannot set fonts or export PDF. Publish to PDF from Archicad's Publisher.</p>
  </fieldset>`;
}

// -- inspector ---------------------------------------------------------------------------

function renderInspector() {
  const el = $('inspector');
  const id = state.selected;
  const r = id && rectOf(state.cfg, id);
  if (!r) {
    el.innerHTML = `<h3 style="margin:0 0 6px">Board</h3><p class="muted">Select a panel, picture, drawing or caption on the board to place it exactly.</p>
      <label class="check"><input type="checkbox" id="moveContents" ${state.moveContents ? 'checked' : ''}> Moving a panel moves what is inside it</label>`;
    return;
  }
  const [kind, key] = splitId(id);
  const t = target(state.cfg, id);
  const title = kind === 'caption' ? `Caption` : `${kind[0].toUpperCase()}${kind.slice(1)} · ${key}`;
  const geo = kind === 'caption'
    ? `<div class="pair"><label>x <input type="number" step="0.25" data-geo="x" value="${t.x}"></label><label>y <input type="number" step="0.25" data-geo="y" value="${t.y}"></label></div>`
    : `<div class="pair"><label>x <input type="number" step="0.25" data-geo="x" value="${r.x}"></label><label>y <input type="number" step="0.25" data-geo="y" value="${r.y}"></label>
       <label>w <input type="number" step="0.25" min="1" data-geo="w" value="${r.w}"></label><label>h <input type="number" step="0.25" min="1" data-geo="h" value="${r.h}"></label></div>`;
  let extra = '';
  if (kind === 'drawing') {
    const d = state.cfg.drawings.find((x) => x.key === key);
    extra = `<p class="muted" style="margin:0">${esc(d.name)} · ${d.fit ? 'fitted' : `1:${d.scale}`}</p>`;
  } else if (kind === 'image') {
    const pic = state.pictures[key];
    extra = `<p class="muted" style="margin:0">${pic ? `${esc(pic.name)}, ${pic.w} × ${pic.h} px` : 'No picture yet. Drop one on the slot or use the Sources tab.'}</p>`;
  } else if (kind === 'caption') {
    extra = `<input type="text" data-bind="captions.${key}.text" value="${esc(t.text)}" aria-label="Caption text">`;
  }
  el.innerHTML = `<h3 style="margin:0 0 6px">${esc(title)}</h3>
    <div class="inspector-geo" style="display:flex;flex-direction:column;gap:8px">${geo}${extra}
    <p class="muted" style="margin:0">Millimetres from the page's top-left corner.</p>
    <label class="check"><input type="checkbox" id="moveContents" ${state.moveContents ? 'checked' : ''}> Moving a panel moves what is inside it</label>
    <button type="button" data-action="deselect">Done</button></div>`;
}

// -- board -----------------------------------------------------------------------------

let frame = 0;
function renderBoard() {
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(() => {
    const host = $('board');
    host.innerHTML = renderSvg(state.cfg, {
      pictures: state.pictures, selected: state.selected, editing: state.editing, showGrid: state.showGrid, showLabels: state.showLabels,
    });
    applyZoom();
  });
}

function fitScale() {
  const wrap = $('canvasWrap');
  const L = state.cfg.layout;
  const pad = 48;
  return Math.max(0.1, Math.min((wrap.clientWidth - pad) / L.width_mm, (wrap.clientHeight - pad) / L.height_mm));
}

function applyZoom() {
  const svg = $('board').querySelector('svg');
  if (!svg) return;
  const L = state.cfg.layout;
  const px = state.zoom || fitScale();
  svg.style.width = `${L.width_mm * px}px`;
  svg.style.height = `${L.height_mm * px}px`;
  $('zoomLabel').textContent = `${Math.round((px / fitScale()) * 100)}%`;
}

function renderStatus() {
  const { errors, warnings } = validate(state.cfg);
  const b = $('statusBtn');
  b.className = `status ${errors.length ? 'err' : warnings.length ? 'warn' : 'ok'}`;
  b.textContent = errors.length ? `${errors.length} error${errors.length > 1 ? 's' : ''}` : warnings.length ? `${warnings.length} warning${warnings.length > 1 ? 's' : ''}` : 'Ready';
}

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove('show'), 2600);
}

function dialog(html) {
  $('dialogContent').innerHTML = html;
  const d = $('dialog');
  if (typeof d.showModal === 'function') d.showModal(); else toast('Dialogs are not supported in this browser.');
}

// -- pointer editing on the board -----------------------------------------------------

function toMm(ev) {
  const svg = $('board').querySelector('svg');
  const r = svg.getBoundingClientRect();
  const L = state.cfg.layout;
  return { x: ((ev.clientX - r.left) / r.width) * L.width_mm, y: ((ev.clientY - r.top) / r.height) * L.height_mm };
}

let drag = null;

function onPointerDown(ev) {
  if (!state.editing || ev.button !== 0) return;
  const el = ev.target.closest('[data-id]');
  if (!el) {
    if (state.selected) { state.selected = null; renderBoard(); renderInspector(); }
    return;
  }
  ev.preventDefault();
  const id = el.dataset.id;
  const changedSelection = state.selected !== id;
  state.selected = id;
  const start = toMm(ev);
  const rect = { ...rectOf(state.cfg, id) };
  const kids = id.startsWith('panel:') && state.moveContents ? contained(state.cfg, rect, id).map((it) => ({ id: it.id, x: it.rect.x, y: it.rect.y })) : [];
  drag = {
    id, start, rect, kids, handle: el.dataset.handle || null, before: JSON.stringify(state.cfg),
    g: guides(state.cfg, [id, ...kids.map((k) => k.id)]),
  };
  $('board').setPointerCapture(ev.pointerId);
  if (changedSelection) { renderInspector(); if (['sources', 'content'].includes(state.tab)) renderTab(); }
  renderBoard();
}

function onPointerMove(ev) {
  if (!drag) return;
  const p = toMm(ev);
  const dx = p.x - drag.start.x, dy = p.y - drag.start.y;
  const step = ev.altKey ? 0 : state.cfg.configurator.snap_mm;
  const noSnap = { gx: [], gy: [] };
  const g = ev.altKey ? noSnap : drag.g;
  const r0 = drag.rect;
  if (!drag.handle) {
    const moved = snapMove({ ...r0, x: r0.x + dx, y: r0.y + dy }, g, step);
    const t = target(state.cfg, drag.id);
    t.x = Math.round(moved.x * 100) / 100; t.y = Math.round(moved.y * 100) / 100;
    const ddx = moved.x - r0.x, ddy = moved.y - r0.y;
    for (const k of drag.kids) {
      const kt = target(state.cfg, k.id);
      kt.x = Math.round((k.x + ddx) * 100) / 100; kt.y = Math.round((k.y + ddy) * 100) / 100;
    }
  } else {
    let { x, y, w, h } = r0;
    let x2 = x + w, y2 = y + h;
    const hd = drag.handle;
    if (hd.includes('w')) x = snapValue(r0.x + dx, g.gx, step);
    if (hd.includes('e')) x2 = snapValue(r0.x + r0.w + dx, g.gx, step);
    if (hd.includes('n')) y = snapValue(r0.y + dy, g.gy, step);
    if (hd.includes('s')) y2 = snapValue(r0.y + r0.h + dy, g.gy, step);
    if (ev.shiftKey && hd.length === 2) { // keep proportions from the corner
      const ratio = r0.w / r0.h;
      const nw = x2 - x, nh = nw / ratio;
      if (hd.includes('n')) y = y2 - nh; else y2 = y + nh;
    }
    if (x2 - x < 2) { if (hd.includes('w')) x = x2 - 2; else x2 = x + 2; }
    if (y2 - y < 2) { if (hd.includes('n')) y = y2 - 2; else y2 = y + 2; }
    resizeItem(state.cfg, drag.id, { x, y, w: x2 - x, h: y2 - y });
  }
  renderBoard();
}

function onPointerUp() {
  if (!drag) return;
  const before = drag.before;
  drag = null;
  if (JSON.stringify(state.cfg) !== before) {
    state.history.push(before);
    state.future = [];
    state.lastEdit = { key: '', at: 0 };
    afterChange(false);
  }
}

function nudge(dx, dy) {
  const id = state.selected;
  if (!id) return;
  edit((cfg) => {
    const t = target(cfg, id);
    const r = rectOf(cfg, id);
    const kids = id.startsWith('panel:') && state.moveContents ? contained(cfg, r, id) : [];
    for (const o of [t, ...kids.map((k) => target(cfg, k.id))]) { o.x = Math.round((o.x + dx) * 100) / 100; o.y = Math.round((o.y + dy) * 100) / 100; }
  }, { key: `nudge:${id}` });
}

// -- pictures ---------------------------------------------------------------------------

async function setPicture(key, file) {
  try {
    const pic = await loadPicture(file, file.name || key);
    const old = state.pictures[key];
    if (old) URL.revokeObjectURL(old.url);
    state.pictures[key] = pic;
    await savePicture(key, pic);
    edit((cfg) => {
      const img = cfg.images.find((i) => i.key === key);
      if (img && file.name && !img.source) img.source = file.name;
    });
    renderBoard(); renderStatus();
    if (state.tab === 'sources' || state.tab === 'build') renderTab();
    renderInspector();
    toast(`Picture set for ${key}.`);
  } catch (e) {
    toast(e.message);
  }
}

async function clearPicture(key) {
  const old = state.pictures[key];
  if (old) URL.revokeObjectURL(old.url);
  delete state.pictures[key];
  await deletePicture(key);
  renderBoard(); renderStatus(); renderTab(); renderInspector();
}

// -- export ---------------------------------------------------------------------------

function download(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function croppedPictures(dpi) {
  const out = {};
  for (const img of state.cfg.images) {
    const pic = state.pictures[img.key];
    if (pic) out[img.key] = cropToDataUrl(img, pic, dpi);
  }
  return out;
}

function exportPackage() {
  const { errors } = validate(state.cfg);
  if (errors.length) {
    dialog(`<h3 style="margin:0">Fix these first</h3><ul class="list">${errors.map((e) => `<li class="err">${esc(e)}</li>`).join('')}</ul>`);
    return;
  }
  const pictures = croppedPictures(state.dpi);
  const pkg = toPackage(state.cfg, pictures, GENERATOR);
  const name = `${fileBase(state.cfg)}.board.json`;
  download(name, new Blob([JSON.stringify(pkg, null, 1)], { type: 'application/json' }));
  const n = Object.keys(pictures).length;
  toast(`Downloaded ${name} with ${n} of ${state.cfg.images.length} pictures inside.`);
}

function exportConfig() {
  const cfg = toConfig(state.cfg);
  download('board.json', new Blob([JSON.stringify(cfg, null, 2) + '\n'], { type: 'application/json' }));
}

function exportScript() {
  const a = document.createElement('a');
  a.href = 'archicad/BuildBoard.py'; a.download = 'BuildBoard.py';
  document.body.appendChild(a); a.click(); a.remove();
}

async function exportPng() {
  try {
    const pics = {};
    const cropped = croppedPictures(100);
    for (const img of state.cfg.images) if (cropped[img.key]) pics[img.key] = { url: cropped[img.key], w: img.w, h: img.h };
    // Cropped pictures already match their slots, so place them unscaled.
    const cfg = clone(state.cfg);
    for (const img of cfg.images) img.crop = { fx: 0.5, fy: 0.5, zoom: 1 };
    const svg = renderSvg(cfg, { pictures: pics, editing: false });
    const L = state.cfg.layout;
    const width = 2400, height = Math.round(width * L.height_mm / L.width_mm);
    const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
    const im = new Image();
    im.src = url;
    await im.decode();
    const c = document.createElement('canvas');
    c.width = width; c.height = height;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, width, height);
    ctx.drawImage(im, 0, 0, width, height);
    URL.revokeObjectURL(url);
    c.toBlob((blob) => blob ? download(`${fileBase(state.cfg)}-preview.png`, blob) : toast('This browser could not make the image.'), 'image/png');
  } catch {
    toast('This browser could not make the preview image.');
  }
}

async function importFile(file) {
  try {
    const doc = JSON.parse(await file.text());
    if (!doc?.layout || !doc.panels) throw new Error('This is not a board config.');
    const embedded = (doc.images || []).filter((i) => i.data);
    loadConfig(doc, { keepHistory: true });
    for (const img of embedded) {
      try {
        const pic = await pictureFromDataUrl(img.data, img.file);
        if (state.pictures[img.key]) URL.revokeObjectURL(state.pictures[img.key].url);
        state.pictures[img.key] = pic;
        await savePicture(img.key, pic);
        // Embedded pictures are already cropped to their slots.
        const live = state.cfg.images.find((i) => i.key === img.key);
        if (live) live.crop = { fx: 0.5, fy: 0.5, zoom: 1 };
      } catch { /* keep going without that picture */ }
    }
    afterChange(true);
    toast(`Opened ${file.name}.`);
  } catch (e) {
    toast(`Could not open ${file.name}: ${e.message}`);
  }
}

async function loadPreset(id) {
  const p = state.presets.find((x) => x.id === id);
  if (!p) return;
  try {
    const res = await fetch(`presets/${p.file}`, { cache: 'no-cache' });
    if (!res.ok) throw new Error(res.statusText);
    loadConfig(await res.json(), { keepHistory: true });
    toast(`Loaded ${p.title}. Undo brings back the previous board.`);
  } catch (e) {
    toast(`Could not load the preset: ${e.message}`);
  }
}

// -- actions ----------------------------------------------------------------------------

function onAction(el) {
  const a = el.dataset.action;
  const i = Number(el.dataset.index);
  switch (a) {
    case 'select': state.selected = el.dataset.id; renderBoard(); renderInspector(); renderTab(); break;
    case 'deselect': state.selected = null; renderBoard(); renderInspector(); break;
    case 'page-apply': applyPageSize(Number($('pageW').value), Number($('pageH').value)); break;
    case 'page-rotate': applyPageSize(state.cfg.layout.height_mm, state.cfg.layout.width_mm); break;
    case 'add-caption': edit((c) => c.captions.push({ text: 'Caption', x: c.border.inset_x_mm + 15, y: c.border.inset_y_mm + 15 }), { forms: true }); break;
    case 'remove-caption': edit((c) => c.captions.splice(i, 1), { forms: true }); state.selected = null; break;
    case 'add-placeholder': edit((c) => c.placeholders.push({ key: freshKey(c.placeholders, 'placeholder'), x: c.border.inset_x_mm + 15, y: c.border.inset_y_mm + 15, w: 80, h: 60, text: '[Picture to come]', caption: 'Caption' }), { forms: true }); break;
    case 'remove-placeholder': edit((c) => c.placeholders.splice(i, 1), { forms: true }); state.selected = null; break;
    case 'add-image': edit((c) => {
      const key = freshKey(c.images, 'picture');
      c.images.push({ key, file: `${fileBase(c)}_${key}.jpg`.replace(/[^A-Za-z0-9_.-]/g, '_'), x: c.border.inset_x_mm + 15, y: c.border.inset_y_mm + 15, w: 100, h: 70, crop: { fx: 0.5, fy: 0.5, zoom: 1 } });
    }, { forms: true }); break;
    case 'remove-image': { const key = state.cfg.images[i]?.key; edit((c) => c.images.splice(i, 1), { forms: true }); if (key) clearPicture(key); state.selected = null; break; }
    case 'add-drawing': edit((c) => {
      const key = freshKey(c.drawings, 'drawing');
      c.drawings.push({ key, name: `${c.layout.id} ${key}`, source: '', scale: 200, slot: { x: c.border.inset_x_mm + 15, y: c.border.inset_y_mm + 15, w: 120, h: 80 }, caption: `${key}   1:200` });
    }, { forms: true }); break;
    case 'remove-drawing': edit((c) => c.drawings.splice(i, 1), { forms: true }); state.selected = null; break;
    case 'clear-picture': clearPicture(el.dataset.key); break;
    case 'export-package': exportPackage(); break;
    case 'export-config': exportConfig(); break;
    case 'export-script': exportScript(); break;
    case 'export-png': exportPng(); break;
    case 'copy': {
      const text = $(el.dataset.target)?.textContent || '';
      navigator.clipboard?.writeText(text).then(() => toast('Copied.'), () => toast('Copy is blocked here; select the text instead.'));
      break;
    }
    default: break;
  }
}

function applyPageSize(w, h) {
  if (!(w >= 50 && h >= 50 && w <= 5000 && h <= 5000)) { toast('Page size must be between 50 and 5000 mm.'); return; }
  const scale = $('scaleContent') ? $('scaleContent').checked : true;
  edit((c) => setPageSize(c, w, h, scale), { forms: true });
}

function onBoundInput(el, ev) {
  const path = el.dataset.bind;
  const value = readInput(el);
  if (value === undefined) return; // incomplete entry, e.g. a model clip being typed
  edit((cfg) => {
    if (value === null && ['number', 'int'].includes(el.dataset.type)) return;
    if (path.endsWith('.model_clip') && value === null) { delete getPath(cfg, path.replace(/\.model_clip$/, '')).model_clip; return; }
    if (path.endsWith('.shape') && value === 'rect') { delete getPath(cfg, path.replace(/\.shape$/, '')).shape; return; }
    if (path.endsWith('.fit') && value === false) { delete getPath(cfg, path.replace(/\.fit$/, '')).fit; return; }
    if (path.startsWith('project.explanation.')) {
      const n = Number(path.split('.').pop());
      while (cfg.project.explanation.length <= n) cfg.project.explanation.push('');
    }
    setPath(cfg, path, value);
  }, { key: path, forms: ev.type === 'change' && (el.type === 'checkbox' || el.tagName === 'SELECT') && !path.startsWith('fonts.') });
  if (el.type === 'color' || (el.type === 'text' && /\.hex$/.test(path))) {
    // keep the colour picker and hex field of a pen in step
    document.querySelectorAll(`[data-bind="${CSS.escape(path)}"]`).forEach((o) => { if (o !== el && /^#[0-9a-f]{6}$/i.test(el.value)) o.value = el.value; });
  }
}

function onGeoInput(el) {
  const id = state.selected;
  if (!id) return;
  const v = parseFloat(el.value);
  if (!Number.isFinite(v)) return;
  edit((cfg) => {
    const t = target(cfg, id);
    const k = el.dataset.geo;
    if (id.startsWith('panel:') && state.moveContents && (k === 'x' || k === 'y')) {
      const r = rectOf(cfg, id);
      const d = v - r[k];
      for (const kid of contained(cfg, r, id)) target(cfg, kid.id)[k] = Math.round((target(cfg, kid.id)[k] + d) * 100) / 100;
    }
    t[k] = (k === 'w' || k === 'h') ? Math.max(1, v) : v;
  }, { key: `geo:${id}:${el.dataset.geo}` });
}

// -- wiring -----------------------------------------------------------------------------

function wire() {
  document.querySelector('.tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab]');
    if (!b) return;
    state.tab = b.dataset.tab; saveUi(); renderTab();
  });
  for (const root of [$('tabBody'), $('inspector')]) {
    root.addEventListener('input', (e) => {
      const el = e.target;
      if (el.dataset.bind && el.type !== 'checkbox' && el.tagName !== 'SELECT') onBoundInput(el, e);
      else if (el.dataset.geo) onGeoInput(el);
    });
    root.addEventListener('change', (e) => {
      const el = e.target;
      if (el.dataset.bind && (el.type === 'checkbox' || el.tagName === 'SELECT')) onBoundInput(el, e);
      else if (el.dataset.picture && el.files?.[0]) setPicture(el.dataset.picture, el.files[0]);
      else if (el.id === 'dpi') { state.dpi = Number(el.value); saveUi(); }
      else if (el.id === 'moveContents') { state.moveContents = el.checked; saveUi(); }
      else if (el.id === 'pagePreset' && el.value) {
        const p = PAGE_PRESETS.find((x) => x.id === el.value);
        const landscape = state.cfg.layout.width_mm > state.cfg.layout.height_mm;
        applyPageSize(landscape ? p.h : p.w, landscape ? p.w : p.h);
      }
    });
    root.addEventListener('click', (e) => {
      const el = e.target.closest('[data-action]');
      if (el) onAction(el);
    });
    root.addEventListener('dragover', (e) => { const d = e.target.closest('[data-drop]'); if (d) { e.preventDefault(); d.classList.add('over'); } });
    root.addEventListener('dragleave', (e) => { e.target.closest('[data-drop]')?.classList.remove('over'); });
    root.addEventListener('drop', (e) => {
      const d = e.target.closest('[data-drop]');
      if (!d) return;
      e.preventDefault(); d.classList.remove('over');
      const f = e.dataTransfer.files?.[0];
      if (f) setPicture(d.dataset.drop, f);
    });
  }

  const board = $('board');
  board.addEventListener('pointerdown', onPointerDown);
  board.addEventListener('pointermove', onPointerMove);
  board.addEventListener('pointerup', onPointerUp);
  board.addEventListener('pointercancel', onPointerUp);
  // Drop a picture straight onto its slot.
  const wrap = $('canvasWrap');
  wrap.addEventListener('dragover', (e) => { if (e.dataTransfer?.types?.includes('Files')) e.preventDefault(); });
  wrap.addEventListener('drop', (e) => {
    const f = e.dataTransfer.files?.[0];
    if (!f) return;
    e.preventDefault();
    const svg = board.querySelector('svg');
    if (!svg) return;
    const p = toMm(e);
    const img = state.cfg.images.find((i) => p.x >= i.x && p.x <= i.x + i.w && p.y >= i.y && p.y <= i.y + i.h);
    if (img) setPicture(img.key, f); else toast('Drop the picture on one of the picture slots.');
  });

  document.querySelectorAll('[data-zoom]').forEach((b) => b.addEventListener('click', () => {
    const z = b.dataset.zoom;
    const cur = state.zoom || fitScale();
    state.zoom = z === 'fit' ? 0 : Math.max(0.2, Math.min(12, z === '+' ? cur * 1.25 : cur / 1.25));
    applyZoom();
  }));
  window.addEventListener('resize', () => { if (!state.zoom) applyZoom(); });

  $('gridToggle').addEventListener('change', (e) => { state.showGrid = e.target.checked; saveUi(); renderBoard(); });
  $('labelToggle').addEventListener('change', (e) => { state.showLabels = e.target.checked; saveUi(); renderBoard(); });
  $('editToggle').addEventListener('change', (e) => { state.editing = e.target.checked; if (!state.editing) state.selected = null; renderBoard(); renderInspector(); });
  $('undoBtn').addEventListener('click', undo);
  $('redoBtn').addEventListener('click', redo);
  $('importBtn').addEventListener('click', () => $('importFile').click());
  $('importFile').addEventListener('change', (e) => { const f = e.target.files?.[0]; if (f) importFile(f); e.target.value = ''; });
  $('presetSelect').addEventListener('change', (e) => { if (e.target.value) loadPreset(e.target.value); e.target.value = ''; });
  $('statusBtn').addEventListener('click', () => { state.tab = 'build'; saveUi(); renderTab(); });
  $('exportBtn').addEventListener('click', () => { state.tab = 'build'; saveUi(); renderTab(); });

  document.addEventListener('keydown', (e) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 'z' && !typing) { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (mod && e.key.toLowerCase() === 'y' && !typing) { e.preventDefault(); redo(); return; }
    if (typing || !state.selected) return;
    const step = (e.shiftKey ? 10 : 1) * (state.cfg.configurator.snap_mm || 1);
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) { e.preventDefault(); nudge(...moves[e.key]); }
    if (e.key === 'Escape') { state.selected = null; renderBoard(); renderInspector(); }
  });
}

async function init() {
  const ui = store.get(UI_KEY) || {};
  Object.assign(state, {
    tab: ui.tab || 'page', showGrid: ui.showGrid ?? true, showLabels: ui.showLabels ?? true,
    dpi: ui.dpi || 150, moveContents: ui.moveContents ?? true,
  });
  $('gridToggle').checked = state.showGrid;
  $('labelToggle').checked = state.showLabels;
  wire();
  try {
    state.presets = await (await fetch('presets/index.json', { cache: 'no-cache' })).json();
  } catch { state.presets = []; }
  $('presetSelect').innerHTML = `<option value="">Start from…</option>${state.presets.map((p) => `<option value="${esc(p.id)}">${esc(p.title)} (${esc(p.size)})</option>`).join('')}`;
  const saved = store.get(STORE_KEY);
  if (saved?.layout && saved.panels) {
    state.cfg = normalise(saved);
  } else if (state.presets.length) {
    state.cfg = normalise(await (await fetch(`presets/${state.presets[0].file}`)).json());
  } else {
    document.body.innerHTML = '<p style="padding:24px">The board presets could not be loaded.</p>';
    return;
  }
  state.pictures = await restorePictures();
  afterChange(true);
}

init();
