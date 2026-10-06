import test from 'node:test';
import assert from 'node:assert/strict';
import {matches,normalize,chooseLocale,safeEndpoint} from '../../daily/daily.mjs';
test('search handles English case, Traditional Chinese and Unicode width',()=>{assert.equal(normalize(' ＡＩ '),'ai');assert.ok(matches({text:'AI 人工智慧',category:'papers'},'人工','papers'));assert.ok(matches({text:'AI paper',category:'papers'},'ai PAPER'));assert.ok(!matches({text:'AI',category:'news'},'AI','papers'));});
test('date filters do not invent missing editions',()=>{assert.ok(matches({text:'AI',category:'all',date:'2026-10-04'},'', 'all','2026-10-04'));assert.ok(!matches({text:'AI',date:'2026-10-04'},'','all','2026-10-03'));});
test('language priority and invalid stored values',()=>{assert.equal(chooseLocale('en','zh-TW','zh-TW'),'en');assert.equal(chooseLocale(null,'en','zh-TW'),'en');assert.equal(chooseLocale('x','x','en'),'en');});
test('subscription only permits HTTPS without credentials',()=>{assert.ok(safeEndpoint('https://service.test/subscribe'));for(const url of ['javascript:alert(1)','http://service.test','https://user:pass@service.test'])assert.ok(!safeEndpoint(url));});
