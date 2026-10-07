import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {validateIndex,searchArchive,normalize} from '../../daily/archive-search.mjs';
const index=JSON.parse(readFileSync(new URL('../../daily/data/search-index.json',import.meta.url)));
const issueDirectory=new URL('../../daily/data/issues/',import.meta.url);
const issues=readdirSync(issueDirectory).filter(name=>name.endsWith('.json')).map(name=>JSON.parse(readFileSync(new URL(name,issueDirectory))));
const expectedCount=issues.reduce((sum,issue)=>sum+issue.items.length,0);
test('all reviewed records are searchable without an edition date window',()=>{
  validateIndex(index);assert.equal(index.records.length,expectedCount);assert.equal(searchArchive(index,'').length,expectedCount);
  assert.deepEqual(new Set(index.records.map(r=>r.key)),new Set(issues.flatMap(i=>i.items.map(item=>`${i.date}:${item.id}`))));
  for(const day of ['2026-10-04','2026-10-06','2026-10-07']){
    const row=index.records.find(r=>r.editionDate===day);
    for(const locale of ['zh-TW','en']) for(const field of ['title','summary','takeaway','caveat']) assert.ok(searchArchive(index,row.localized[locale][field]).some(r=>r.key===row.key),`${day}:${locale}:${field}`);
  }
});
test('search normalizes Unicode, matches all terms, handles empty and no results',()=>{
  assert.equal(normalize(' ＡＩ '),'ai');assert.equal(searchArchive(index,' \t\n ').length,expectedCount);
  assert.deepEqual(searchArchive(index,'no-such-token-782912'),[]);
  const row=index.records[0];assert.ok(searchArchive(index,row.source+' '+row.localized.en.title).some(r=>r.key===row.key));
  assert.ok(searchArchive(index,'','papers').every(r=>r.category==='papers'));
});
test('index rejects duplicate keys, unsafe URLs, malformed dates and hidden membership',()=>{
  for(const mutate of [d=>d.records.push(d.records[0]),d=>d.records[0].sourceUrl='data:text/html,x',d=>d.records[0].permalink.en='javascript:x',d=>d.records[0].editionDate='2026-02-30',d=>d.editions.splice(0,1),d=>delete d.records[0].localized.en.summary]){
    const bad=structuredClone(index);mutate(bad);assert.throws(()=>validateIndex(bad));
  }
});
