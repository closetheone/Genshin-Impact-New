import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { catalogPage, catalogAddress } from '../web/real-characters.mjs';

const data = JSON.parse(readFileSync(new URL('../data/characters/genshin-basics-v2.json', import.meta.url)));
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
