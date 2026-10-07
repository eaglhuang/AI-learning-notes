import test from 'node:test';
import assert from 'node:assert/strict';
import {matches,normalize,chooseLocale,safeEndpoint} from '../../daily/daily.mjs';
import {readFileSync} from 'node:fs';
import {validateEmailEdition,summaryContentDigest,renderEmail} from '../../scripts/newsletter/email-service.mjs';
test('search handles English case, Traditional Chinese and Unicode width',()=>{assert.equal(normalize(' ＡＩ '),'ai');assert.ok(matches({text:'AI 人工智慧',category:'papers'},'人工','papers'));assert.ok(matches({text:'AI paper',category:'papers'},'ai PAPER'));assert.ok(!matches({text:'AI',category:'news'},'AI','papers'));});
test('date filters do not invent missing editions',()=>{assert.ok(matches({text:'AI',category:'all',date:'2026-10-04'},'', 'all','2026-10-04'));assert.ok(!matches({text:'AI',date:'2026-10-04'},'','all','2026-10-03'));});
test('language priority and invalid stored values',()=>{assert.equal(chooseLocale('en','zh-TW','zh-TW'),'en');assert.equal(chooseLocale(null,'en','zh-TW'),'en');assert.equal(chooseLocale('x','x','en'),'en');});
test('subscription only permits HTTPS without credentials',()=>{assert.ok(safeEndpoint('https://service.test/subscribe'));for(const url of ['javascript:alert(1)','http://service.test','https://user:pass@service.test'])assert.ok(!safeEndpoint(url));});
test('issue search still uses bilingual text and stays separate from all-history search',()=>{assert.ok(matches({text:'中文摘要 English summary',category:'tools'},'中文 English','tools'));assert.ok(!matches({text:'中文摘要 English summary',category:'tools'},'中文','news'));});
test('email validation matches shared reviewed short-summary exception cases',()=>{
  const fixture=JSON.parse(readFileSync(new URL('./fixtures/summary-exceptions.json',import.meta.url)));
  const baseline=JSON.parse(readFileSync(new URL('../../daily/data/issues/2026-10-07.json',import.meta.url)));
  assert.deepEqual(validateEmailEdition(baseline,fixture.today),[]);
  assert.equal(summaryContentDigest(fixture.base_item,fixture.date),fixture.expected_digest);
  for(const entry of fixture.cases){
    const issue=structuredClone(baseline),item={...structuredClone(fixture.base_item),source:'Offline source',category:'news',published_date:'2026-10-06'};
    issue.date=entry.date??fixture.date;
    for(const [path,value] of Object.entries(entry.set)){const keys=path.split('.');let target=item;for(const key of keys.slice(0,-1))target=target[key];target[keys.at(-1)]=value;}
    if(entry.rebind)item.summary_length_exception.content_sha256=summaryContentDigest(item,issue.date);
    issue.items[0]=item;
    const errors=validateEmailEdition(issue,fixture.today);
    assert.equal(errors.length===0,entry.valid,entry.name+': '+errors.join('; '));
  }
  const rendered=renderEmail(baseline,'en','https://source.test');
  assert.match(rendered.html,/Shorter summary/);
  for(const item of baseline.items)for(const url of item.summary_sources)assert.ok(rendered.text.includes(url));
});
test('legacy email cannot bypass supporting-source URL validation',()=>{
  const issue=JSON.parse(readFileSync(new URL('../../daily/data/issues/2026-10-04.json',import.meta.url)));
  issue.items[0].summary_sources=['javascript:alert(1)'];
  assert.ok(validateEmailEdition(issue).some(e=>e.includes('summary_sources')));
  assert.throws(()=>renderEmail(issue,'en','https://source.test'));
  issue.items[0].summary_sources=['https://source.test/verified'];
  assert.deepEqual(validateEmailEdition(issue),[]);
  issue.items[0].summary_length_exception={reviewed:true};
  assert.ok(validateEmailEdition(issue).some(e=>e.includes('exceptions are unavailable')));
});
