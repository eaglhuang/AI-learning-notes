import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mountArchiveSearch} from '../../daily/archive-search.mjs';
const index=JSON.parse(readFileSync(new URL('../../daily/data/search-index.json',import.meta.url)));
function dom(){
  const doc={activeElement:null};
  class El{
    constructor(tag){this.tag=tag;this.children=[];this.events={};this.attrs={};this.value='';this.ownerDocument=doc;this.textContent='';}
    append(...els){this.children.push(...els);if(this.tag==='select'&&this.value==='')this.value=els[0].value;}
    replaceChildren(...els){this.children=[];this.append(...els);}
    setAttribute(k,v){this.attrs[k]=v;}
    addEventListener(k,f){this.events[k]=f;}
    focus(){doc.activeElement=this;}
    get options(){return this.children;}
    set innerHTML(value){assert.fail('Untrusted data must never become HTML');}
  }
  doc.createElement=tag=>new El(tag);
  return {doc,root:new El('section')};
}
const flatten=node=>[node,...node.children.flatMap(flatten)];
test('archive controls retain query/category/active summary across language changes, reset and safe rendering',()=>{
  const {root,doc}=dom(),opened=[];
  const malicious=structuredClone(index),chosen=malicious.records.find(r=>r.storyId==='openai-ironclad-evaluation-2026-10-06');chosen.localized.en.title='<img onerror=alert(1)>';
  const ui=mountArchiveSearch({root,index:malicious,controller:{supported:true,open(row,button){opened.push([row,button]);}}});
  const input=flatten(root).find(n=>n.tag==='input'),select=flatten(root).find(n=>n.tag==='select');
  input.value='Ironclad';input.events.input();
  select.value=chosen.category;select.events.change();
  const summary=flatten(root).find(n=>n.tag==='button'&&n.textContent==='閱讀摘要');summary.events.click();assert.equal(opened.length,1);
  ui.setLocale('en');assert.equal(input.value,'Ironclad');assert.equal(select.value,chosen.category);assert.equal(opened.length,1);
  assert.ok(flatten(root).some(n=>n.tag==='a'&&n.textContent.includes('<img onerror')));
  assert.ok(flatten(root).some(n=>n.tag==='button'&&n.disabled));
  input.value='no-such-term';input.events.input();assert.ok(flatten(root).some(n=>n.textContent.startsWith('No matches')));
  const reset=flatten(root).find(n=>n.tag==='button'&&n.textContent==='Reset');reset.events.click();assert.equal(input.value,'');assert.equal(select.value,'all');assert.equal(doc.activeElement,input);
  assert.equal(flatten(root).filter(n=>n.tag==='article').length,index.records.length);
});
test('unsupported dialog uses closed details with full saved text',()=>{
  const {root}=dom();mountArchiveSearch({root,index,locale:'en',controller:{supported:false}});
  const details=flatten(root).filter(n=>n.tag==='details');assert.equal(details.length,index.records.length);
  assert.equal(details[0].children[1].textContent,index.records[0].localized.en.summary);assert.equal(details[0].attrs.open,undefined);
});
