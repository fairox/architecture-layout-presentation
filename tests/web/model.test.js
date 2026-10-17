import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  clone, contained, drawingPaperSize, gridLines, imagePlacement, items, normalise, setPageSize,
  snapMove, snapValue, texts, toConfig, toPackage, validate, wrap,
} from '../../web/js/model.js';
import { renderSvg } from '../../web/js/preview.js';

const preset = JSON.parse(readFileSync(new URL('../../web/presets/pres-01.json', import.meta.url), 'utf8'));
const board = () => normalise(preset);

test('the PRES-01 preset validates with no errors or warnings', () => {
  const { errors, warnings } = validate(board());
  assert.deepEqual(errors, []);
  assert.deepEqual(warnings, []);
});

test('normalise adds configurator defaults and keeps builder keys unchanged', () => {
  const cfg = board();
  assert.equal(cfg.configurator.columns, 12);
  assert.equal(cfg.images.find((i) => i.key === 'context').shape, 'circle');
  const back = toConfig(cfg);
  for (const k of ['layout', 'pens', 'panels', 'drawings', 'project', 'border', 'type_mm']) assert.deepEqual(back[k], preset[k]);
});

test('validation catches what would break the builder', () => {
  const cases = [
    [(c) => { delete c.pens.grey; }, /pen named 'grey'/],
    [(c) => { c.pens.cream.index = c.pens.grey.index; }, /both use pen/],
    [(c) => { c.images = c.images.filter((i) => i.key !== 'hero'); }, /key 'hero'/],
    [(c) => { c.images[0].file = '../evil.jpg'; }, /plain \.jpg/],
    [(c) => { c.drawings[0].source = 'not-a-guid'; }, /navigator id/],
    [(c) => { c.drawings[0].model_clip = [1, 0, 0, 1]; }, /model_clip/],
    [(c) => { c.panels.hero.x = 590; }, /runs off/],
    [(c) => { c.project.principles = []; }, /at least one row/],
    [(c) => { c.images.find((i) => i.key === 'hero').y = 10; }, /title band/],
  ];
  for (const [mutate, pattern] of cases) {
    const cfg = board();
    mutate(cfg);
    const { errors } = validate(cfg);
    assert.ok(errors.some((e) => pattern.test(e)), `expected ${pattern} in ${JSON.stringify(errors)}`);
  }
});

test('a drawing larger than its slot is a warning with its paper size', () => {
  const cfg = board();
  const plan = cfg.drawings.find((d) => d.key === 'plan-5');
  assert.deepEqual(drawingPaperSize(plan), { w: (84.5 + 2) / 750 * 1000, h: (37.5 + 4) / 750 * 1000 });
  plan.scale = 500;
  assert.ok(validate(cfg).warnings.some((w) => /plan-5.*more than its/.test(w)));
});

test('scaling the page scales positions, sizes, insets and type together', () => {
  const cfg = setPageSize(board(), 1200, 1500, true);
  assert.equal(cfg.panels.hero.w, preset.panels.hero.w * 2);
  assert.equal(cfg.border.inset_x_mm, preset.border.inset_x_mm * 2);
  assert.equal(cfg.type_mm.title, preset.type_mm.title * 2);
  assert.deepEqual(validate(cfg).errors, []);
  const fixed = setPageSize(board(), 841, 1189, false);
  assert.equal(fixed.panels.hero.x, preset.panels.hero.x);
});

test('pictures are cropped to cover their slot, never stretched', () => {
  const slot = { x: 10, y: 20, w: 100, h: 50 };
  const p = imagePlacement(slot, { w: 400, h: 400 }, { fx: 0.5, fy: 0.5, zoom: 1 });
  assert.equal(p.w, p.h); // aspect kept
  assert.ok(p.x <= slot.x && p.y <= slot.y && p.x + p.w >= slot.x + slot.w && p.y + p.h >= slot.y + slot.h);
  assert.equal(p.source.w / p.source.h, 2); // source window has the slot's proportions
  const edge = imagePlacement(slot, { w: 400, h: 400 }, { fx: 0, fy: 0, zoom: 1 });
  assert.equal(edge.x, slot.x); // focus clamps so the slot stays covered
});

test('snapping prefers guides, then the snap step', () => {
  assert.equal(snapValue(100.6, [101], 0.75), 101);
  assert.equal(snapValue(50.4, [], 0.75), 50.25);
  const moved = snapMove({ x: 32.2, y: 90.3, w: 10, h: 10 }, { gx: [33], gy: [100] }, 0.5);
  assert.equal(moved.x, 33);
  assert.equal(moved.y + moved.h, 100);
});

test('grid columns fill the border box with gutters', () => {
  const cfg = board();
  const { xs } = gridLines(cfg);
  assert.equal(xs.length, cfg.configurator.columns * 2);
  assert.equal(xs[0], cfg.border.inset_x_mm);
  assert.ok(Math.abs(xs[xs.length - 1] - (cfg.layout.width_mm - cfg.border.inset_x_mm)) < 1e-9);
});

test('a panel contains the items inside it', () => {
  const cfg = board();
  const ids = contained(cfg, cfg.panels.plans, 'panel:plans').map((i) => i.id);
  assert.ok(['plan-5', 'plan-3', 'plan-2', 'plan-0', 'plan-b'].every((k) => ids.includes(`drawing:${k}`)));
  assert.ok(items(cfg).length > 20);
});

test('text placement mirrors the builder', () => {
  const cfg = board();
  const t = Object.fromEntries(texts(cfg).map((x) => [x.key, x]));
  assert.equal(t.title.x, cfg.panels.hero.x + 10);
  assert.equal(t.location.y, cfg.panels.hero.y + 8 + cfg.type_mm.title * 1.6 * 2 + 2);
  assert.equal(t.credit.y, cfg.layout.height_mm - cfg.border.inset_y_mm - 6);
  assert.equal(t['principle-number-3'].anchor, 'MiddleMiddle');
  // Same wrap width rule as textwrap.fill in board.py
  assert.ok(wrap('a '.repeat(80), 50, 3.7).split('\n').every((l) => l.length <= Math.floor(50 / (3.7 * 0.68))));
});

test('the package embeds image data and the config does not', () => {
  const cfg = board();
  const pkg = toPackage(cfg, { hero: 'data:image/jpeg;base64,AAAA' }, 'test');
  assert.equal(pkg.format, 'archicad-board');
  assert.equal(pkg.images.find((i) => i.key === 'hero').data, 'data:image/jpeg;base64,AAAA');
  assert.equal(toConfig(clone(pkg)).images.find((i) => i.key === 'hero').data, undefined);
  assert.deepEqual(validate(pkg).errors, []);
});

test('the preview renders every slot and escapes text', () => {
  const cfg = board();
  cfg.project.title_lines = ['<script>alert(1)</script>'];
  const svg = renderSvg(cfg, { editing: true, selected: 'panel:hero', showGrid: true, showLabels: true });
  assert.ok(svg.startsWith('<svg'));
  assert.ok(!svg.includes('<script>'));
  assert.equal((svg.match(/class="handle /g) || []).length, 8);
  for (const d of cfg.drawings) assert.ok(svg.includes(`data-id="drawing:${d.key}"`));
});
