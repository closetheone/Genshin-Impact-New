import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { catalogPage, catalogAddress, renderRealCharacters, portraitHTML, bindPortraits } from '../web/real-characters.mjs';

const data = JSON.parse(readFileSync(new URL('../data/characters/genshin-basics-v2.json', import.meta.url)));
const references = JSON.parse(readFileSync(new URL('../data/characters/official-character-links-v1.json', import.meta.url)));
const art = JSON.parse(readFileSync(new URL('../data/characters/official-character-art-v1.json', import.meta.url)));

function detailHTML(name, supplement) {
  const originalHistory = globalThis.history;
  const originalDocument = globalThis.document;
  globalThis.history = { replaceState() {} };
  globalThis.document = { querySelectorAll() { return []; } };
  let html;
  try {
    renderRealCharacters({ ...data, character: data.characters.find(c => c.name === name), official_links: supplement }, true, value => { html = value; });
  } finally {
    if (originalHistory === undefined) delete globalThis.history;
    else globalThis.history = originalHistory;
    if (originalDocument === undefined) delete globalThis.document;
    else globalThis.document = originalDocument;
  }
  return html;
}

test('detail links point at the matched official character in a separate tab', () => {
  const html = detailHTML('神里绫华', { ...references, status: 'available' });
  assert.match(html, /href="https:\/\/ys\.mihoyo\.com\/main\/character\/inazuma\?char=0" target="_blank" rel="noopener noreferrer"/u);
  assert.match(html, /前往官网查看神里绫华/u);
  assert.match(html, /官网简介不等于完整角色故事/u);
  assert.match(html, /入口核对于 2026-10-15/u);
  assert.doesNotMatch(html, /<img\b/u);
});

test('directory uses lightweight thumbnails, detail uses attributed full art', () => {
  const character = data.characters.find(c => c.name === '神里绫华');
  const record = art.records.find(r => r.name === character.name);
  const enriched = { ...data, official_art: { ...art, status: 'available' } };
  const card = portraitHTML(enriched, character);
  const detail = portraitHTML(enriched, character, true);
  assert.ok(card.includes(`src="${record.thumbnail_url}"`));
  assert.ok(!card.includes(record.portrait_url));
  assert.match(card, /loading="lazy"/u);
  assert.match(card, /referrerpolicy="no-referrer"/u);
  assert.ok(detail.includes(`src="${record.portrait_url}"`));
  assert.ok(detail.includes(`href="${record.source_url}"`));
  assert.match(detail, /© miHoYo/u);
  assert.match(detail, /loading="eager"/u);
  assert.match(detail, /data-portrait-retry hidden/u);
  assert.doesNotMatch(portraitHTML(enriched, { ...character, name: '另一个角色' }), /<img\b/u);
});

function imageFrame(complete = false, naturalWidth = 0) {
  const img = Object.assign(new EventTarget(), { complete, naturalWidth, src: 'https://example.test/art.png',
    getAttribute() { return this.src; }, removeAttribute() { this.src = null; }, setAttribute(key, value) { this.src = value; } });
  const retry = Object.assign(new EventTarget(), { hidden: true });
  const status = { textContent: '' };
  const frame = { dataset: {}, setAttribute(key, value) { this[key] = value; },
    querySelector(selector) { return selector === 'img' ? img : selector === '[data-portrait-retry]' ? retry : status; } };
  bindPortraits({ querySelectorAll() { return [frame]; } });
  return { frame, img, retry, status };
}

test('failed images show fallback, retry, then recover when loaded', () => {
  const { frame, img, retry, status } = imageFrame();
  img.dispatchEvent(new Event('error'));
  assert.equal(frame.dataset.portraitState, 'error');
  assert.match(status.textContent, /图片暂不可用/u);
  assert.equal(retry.hidden, false);
  retry.dispatchEvent(new Event('click'));
  assert.equal(frame.dataset.portraitState, 'loading');
  assert.equal(frame['aria-busy'], 'true');
  assert.equal(img.src, 'https://example.test/art.png');
  img.dispatchEvent(new Event('load'));
  assert.equal(frame.dataset.portraitState, 'loaded');
  assert.equal(frame['aria-busy'], 'false');
  assert.equal(retry.hidden, true);
});

test('already cached successes and errors settle without waiting for a missed event', () => {
  assert.equal(imageFrame(true, 106).frame.dataset.portraitState, 'loaded');
  assert.equal(imageFrame(true, 0).frame.dataset.portraitState, 'error');
});

test('missing matches and unavailable references keep facts without inventing links', () => {
  const missing = detailHTML('空', { ...references, status: 'available' });
  assert.match(missing, /尚未匹配到此角色的官网展示入口/u);
  assert.doesNotMatch(missing, /href="https:\/\/ys\.mihoyo\.com/u);
  for (const supplement of [undefined, { status: 'unavailable', records: [] }]) {
    const unavailable = detailHTML('神里绫华', supplement);
    assert.match(unavailable, /官网展示入口暂不可用/u);
    assert.match(unavailable, /神里绫华/u);
    assert.doesNotMatch(unavailable, /href="https:\/\/ys\.mihoyo\.com/u);
  }
});
test('pagination covers all records once, including the last partial page', () => {
  const ids = [];
  for (let page = 1; page <= 6; page++) {
    const result = catalogPage(data.characters, { page });
    assert.equal(result.pages, 6);
    assert.equal(result.total, 124);
    assert.ok(result.records.length <= 24);
    ids.push(...result.records.map(c => c.id));
  }
  assert.equal(ids.length, 124);
  assert.equal(new Set(ids).size, 124);
  assert.equal(catalogPage(data.characters, { page: 999 }).page, 6);
});
test('search and filters intersect and reset an out of range page', () => {
  assert.deepEqual(catalogPage(data.characters, { query: ' 安柏 ', element: '火', region: '蒙德', page: 6 }).records.map(c => c.name), ['安柏']);
  const empty = catalogPage(data.characters, { query: '安柏', element: '冰' });
  assert.equal(empty.total, 0);
  assert.equal(empty.pages, 1);
  assert.ok(catalogPage(data.characters, { query: 'AMBER' }).records.some(c => c.name === '安柏'));
});
test('missing regions and no fixed element are available without invented fields', () => {
  const missing = catalogPage(data.characters, { region: 'missing' });
  assert.equal(missing.total, 13);
  assert.ok(missing.records.every(c => c.region === null));
  const travelers = catalogPage(data.characters, { element: '无' });
  assert.equal(travelers.total, 4);
  assert.ok(travelers.records.some(c => c.name === '空'));
  assert.ok(travelers.records.some(c => c.name === '荧'));
});
test('detail and return links retain the fixed catalog and directory context', () => {
  const selection = { query: '单手剑&空', element: '无', region: 'missing', page: 2 };
  const link = catalogAddress(data.catalog_id, 'genshin:10000005', selection);
  const params = new URLSearchParams(link.split('?')[1]);
  assert.equal(params.get('q'), selection.query);
  assert.equal(params.get('catalog'), data.catalog_id);
  assert.equal(params.get('page'), '2');
  assert.equal(params.get('id'), 'genshin:10000005');
  assert.ok(catalogAddress(data.catalog_id, null, selection).startsWith('#/real-characters?'));
});
