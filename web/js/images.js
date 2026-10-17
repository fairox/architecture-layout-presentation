// Source pictures: loading, keeping them between visits (IndexedDB), and cropping
// them to their slots for export. Cropping uses the same imagePlacement() as the
// preview, so the exported picture is exactly what the board shows.

import { exportPixels, imagePlacement } from './model.js';

const DB = 'board-configurator', STORE = 'pictures';
const MAX_SOURCE_BYTES = 60 * 1024 * 1024;

function openDb() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') { reject(new Error('no IndexedDB')); return; }
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx(mode, fn) {
  try {
    const db = await openDb();
    return await new Promise((resolve, reject) => {
      const t = db.transaction(STORE, mode);
      const out = fn(t.objectStore(STORE));
      t.oncomplete = () => resolve(out?.result);
      t.onerror = () => reject(t.error);
    });
  } catch {
    return undefined; // private windows and blocked storage: pictures simply are not remembered
  }
}

/** Decode a blob into {blob, url, w, h, name}. */
export async function loadPicture(blob, name = 'picture') {
  if (!/^image\/(jpeg|png|webp)$/.test(blob.type)) throw new Error(`${name} is not a JPEG, PNG or WebP picture.`);
  if (blob.size > MAX_SOURCE_BYTES) throw new Error(`${name} is larger than 60 MB.`);
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.decoding = 'async';
  img.src = url;
  try { await img.decode(); } catch { URL.revokeObjectURL(url); throw new Error(`${name} could not be read as a picture.`); }
  return { blob, url, w: img.naturalWidth, h: img.naturalHeight, name, el: img };
}

export async function pictureFromDataUrl(dataUrl, name) {
  const m = /^data:(image\/(?:jpeg|png|webp));base64,(.*)$/s.exec(dataUrl || '');
  if (!m) throw new Error(`${name} is not an embedded JPEG or PNG.`);
  const bin = atob(m[2]);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return loadPicture(new Blob([bytes], { type: m[1] }), name);
}

export const savePicture = (key, pic) => tx('readwrite', (s) => s.put({ blob: pic.blob, name: pic.name }, key));
export const deletePicture = (key) => tx('readwrite', (s) => s.delete(key));

/** Every remembered picture as {key: picture}. */
export async function restorePictures() {
  const out = {};
  const keys = (await tx('readonly', (s) => s.getAllKeys())) || [];
  for (const key of keys) {
    const rec = await tx('readonly', (s) => s.get(key));
    if (!rec?.blob) continue;
    try { out[key] = await loadPicture(rec.blob, rec.name); } catch { /* skip unreadable */ }
  }
  return out;
}

/** Crop a picture to an image slot at `dpi`; returns a JPEG data URL. Circles get a white surround. */
export function cropToDataUrl(img, pic, dpi = 150, quality = 0.9) {
  const px = exportPixels(img, dpi);
  const canvas = document.createElement('canvas');
  canvas.width = px.w; canvas.height = px.h;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, px.w, px.h);
  const { source: s } = imagePlacement({ x: 0, y: 0, w: img.w, h: img.h }, pic, img.crop);
  ctx.imageSmoothingQuality = 'high';
  if (img.shape === 'circle') {
    ctx.beginPath();
    ctx.ellipse(px.w / 2, px.h / 2, px.w / 2, px.h / 2, 0, 0, Math.PI * 2);
    ctx.clip();
  }
  ctx.drawImage(pic.el, s.x, s.y, s.w, s.h, 0, 0, px.w, px.h);
  return canvas.toDataURL('image/jpeg', quality);
}
