import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {editionToday,validateEmailEdition,renderEmail} from '../../scripts/newsletter/email-service.mjs';

const read = path => JSON.parse(readFileSync(new URL(path,import.meta.url),'utf8'));
const fixtures=read('./fixtures/source-readiness.json');
const original=read('../../daily/data/issues/2026-10-04.json');
test('newsletter date uses shared Taipei boundaries independently of host timezone',()=>{
  for(const row of fixtures.calendar_cases)assert.equal(editionToday(new Date(row.instant)),row.date,row.instant);
});
test('existing email validation and rendering accept Taipei today and reject tomorrow',()=>{
  const RealDate=globalThis.Date;
  class FixedDate extends RealDate { constructor(...args){super(...(args.length?args:['2026-10-04T16:30:00Z']));} }
  try{
    globalThis.Date=FixedDate;
    const issue=structuredClone(original);issue.date='2026-10-05';issue.reviewed_on='2026-10-05';
    assert.deepEqual(validateEmailEdition(issue),[]);
    assert.ok(renderEmail(issue,'en','https://example.test').subject.startsWith('2026-10-05'));
    issue.date='2026-10-06';
    assert.ok(validateEmailEdition(issue).some(e=>e.includes('non-future')));
  }finally{globalThis.Date=RealDate;}
});
test('reviewed short-summary dates use the same Taipei clock',()=>{
  const RealDate=globalThis.Date;
  class FixedDate extends RealDate { constructor(...args){super(...(args.length?args:['2026-10-06T16:00:00Z']));} }
  try{
    globalThis.Date=FixedDate;
    assert.deepEqual(validateEmailEdition(read('../../daily/data/issues/2026-10-07.json')),[]);
  }finally{globalThis.Date=RealDate;}
});
