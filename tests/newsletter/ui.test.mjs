import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {weekdayForDate, safeHttps, validateRecord, createSummaryController, bindIssueUI} from '../../daily/issue-ui.mjs';
const read = name => JSON.parse(readFileSync(new URL(name, import.meta.url)));
const rows = read('../../daily/data/search-index.json').records.filter(r => r.editionDate === '2026-10-07');

function fixture() {
  const doc = {body:{style:{overflow:'auto'}},documentElement:{classList:{add(){}}},activeElement:null};
  const make = () => ({textContent:'',dataset:{},attrs:{},hidden:false,isConnected:true,events:{},setAttribute(k,v){this.attrs[k]=v;},addEventListener(k,f){this.events[k]=f;},focus(){doc.activeElement=this;}});
  const selectors = ['#summary-title','[data-dialog-summary]','[data-dialog-takeaway]','[data-dialog-caveat]','[data-dialog-meta]','[data-dialog-source]','[data-dialog-close]','[data-dialog-language]'];
  const nodes = Object.fromEntries(selectors.map(s => [s,make()]));
  const controls = [nodes['[data-dialog-language]'],nodes['[data-dialog-close]'],nodes['[data-dialog-source]']];
  const dialog = Object.assign(make(), {open:false,showModal(){this.open=true;},close(){this.open=false;this.events.close?.();},querySelector(s){return nodes[s];},querySelectorAll(){return controls;},getBoundingClientRect(){return {left:10,top:10,right:700,bottom:600};}});
  const fallback = make(); doc.querySelector = s => s === '#summary-dialog' ? dialog : fallback;
  const win = {scrollX:0,scrollY:1234,calls:[],scrollTo(value){this.calls.push(value);}};
  return {doc,win,dialog,nodes,controls,make,fallback};
}

test('calendar weekday is stable across seven dates and rejects normalized invalid dates', () => {
  for (const entry of read('./fixtures/weekly-layouts.json')) assert.equal(weekdayForDate(entry.date),entry.weekday);
  for (const value of ['2026-02-30','2026-10-07T00:00:00+08:00','10/07/2026','']) assert.throws(() => weekdayForDate(value));
});
test('source and permalink links reject script, credentials, whitespace and backslash', () => {
  for (const value of ['javascript:alert(1)','http://source.test','https://user:pass@source.test','https://source.test\\@evil.test/','https://source.test/\n']) assert.equal(safeHttps(value),'');
  assert.equal(safeHttps('https://source.test/'), 'https://source.test/');
  const row = structuredClone(rows[0]); row.permalink.en='javascript:alert(1)'; assert.throws(() => validateRecord(row));
});
test('98 full-summary operations retain exact bilingual text and restore focus/scroll', () => {
  let count=0;
  for (let layout=0;layout<7;layout++) for (const locale of ['zh-TW','en']) for (const row of rows) {
    const f=fixture(), from=f.make();
    const ui=createSummaryController({document:f.doc,window:f.win,locale});
    assert.ok(ui.open(row,from)); assert.equal(ui.activeKey(),row.key);
    for (const field of ['summary','takeaway','caveat']) assert.equal(f.nodes[`[data-dialog-${field}]`].textContent,row.localized[locale][field]);
    assert.equal(f.doc.body.style.overflow,'hidden'); assert.equal(f.dialog.open,true);
    ui.close(); ui.close();
    assert.equal(f.doc.activeElement,from); assert.equal(f.doc.body.style.overflow,'auto'); assert.equal(f.win.calls.length,1); assert.equal(f.win.calls[0].top,1234); count++;
  }
  assert.equal(count,98);
});
test('open dialog switches language, refuses forged content, and can reopen another story', () => {
  const f=fixture(),ui=createSummaryController({document:f.doc,window:f.win});
  ui.open(rows[0],f.make()); ui.setLocale('en'); assert.equal(f.nodes['[data-dialog-summary]'].textContent,rows[0].localized.en.summary);
  const attack=structuredClone(rows[1]);attack.localized.en.summary='<img src=x onerror=alert(1)>';
  ui.open(attack,f.make()); assert.equal(f.nodes['[data-dialog-summary]'].textContent,attack.localized.en.summary);
  assert.equal(ui.activeKey(),rows[1].key);ui.close();
  attack.sourceUrl='javascript:alert(1)';assert.throws(()=>ui.open(attack,f.make()));assert.equal(f.dialog.open,false);
});
test('Esc, backdrop, focus trap and disconnected opener have bounded behavior', () => {
  const f=fixture(),ui=createSummaryController({document:f.doc,window:f.win}),from=f.make();ui.open(rows[0],from);
  let prevented=0;f.controls[0].focus();f.dialog.events.keydown({key:'Tab',shiftKey:true,preventDefault(){prevented++;}});assert.equal(f.doc.activeElement,f.controls.at(-1));
  f.dialog.events.keydown({key:'Tab',shiftKey:false,preventDefault(){prevented++;}});assert.equal(f.doc.activeElement,f.controls[0]);assert.equal(prevented,2);
  f.dialog.events.click({target:f.dialog,clientX:20,clientY:20});assert.equal(f.dialog.open,true);
  f.dialog.events.click({target:f.dialog,clientX:2,clientY:2});assert.equal(f.dialog.open,false);
  ui.open(rows[1],from);from.isConnected=false;f.dialog.events.cancel({preventDefault(){prevented++;}});assert.equal(f.doc.activeElement,f.fallback);assert.equal(ui.activeKey(),null);
});
test('missing native dialog retains the progressive disclosure fallback', () => {
  const f=fixture();delete f.dialog.showModal;
  const ui=createSummaryController({document:f.doc,window:f.win});assert.equal(ui.supported,false);assert.equal(ui.open(rows[0]),false);
});
test('layout selectors synchronize without closing a summary; repeated image failure keeps its frame', () => {
  const wrapper={dataset:{editionDate:'2026-10-07'}};
  const select=()=>({events:{},addEventListener(k,f){this.events[k]=f;}}),picker=select(),dialogPicker=select();
  const fallback={hidden:true,dataset:{},attrs:{},setAttribute(k,v){this.attrs[k]=v;}};
  const img={complete:true,naturalWidth:0,alt:'English concept',dataset:{altZh:'中文示意圖',altEn:'English concept'},parentElement:{querySelector(){return fallback;}},events:{},addEventListener(k,f){this.events[k]=f;}};
  const doc={querySelector(s){return ({'.enhanced-issue':wrapper,'#issue-content':{textContent:JSON.stringify({records:rows})},'#weekday-layout':picker,'#dialog-layout':dialogPicker})[s];},querySelectorAll(s){return s==='.story-image img'?[img]:[];}};
  bindIssueUI({document:doc,controller:{open(){assert.fail('layout must not open/close a story');}}});
  assert.equal(picker.value,'2');dialogPicker.value='6';dialogPicker.events.change();assert.equal(wrapper.dataset.weekday,'6');assert.equal(picker.value,'6');
  picker.value='99';picker.events.change();assert.equal(wrapper.dataset.weekday,'6');
  img.events.error();assert.equal(img.hidden,true);assert.equal(fallback.hidden,false);assert.equal(fallback.attrs['aria-label'],img.alt);assert.equal(fallback.dataset.ariaZh,'中文示意圖');
});
