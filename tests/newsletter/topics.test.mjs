import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {validateTopic,matchTopic,topicFromFields,topicLabel,fold} from '../../daily/topic-config.mjs';
const cases=JSON.parse(readFileSync(new URL('./fixtures/topic-matches.json',import.meta.url),'utf8'));
for(const item of cases)test('topic matching: '+item.name,()=>{
  const config=Object.fromEntries(Object.entries(item).filter(([k])=>['keywords','english_aliases','match','exclude_keywords'].includes(k)));
  const result=matchTopic(item.title,item.excerpt,validateTopic(config));assert.equal(result.eligible,item.eligible);assert.deepEqual(result.matched_terms,item.matched_terms);
});
test('export fields preserve aliases and default general mode',()=>{
  assert.equal(topicFromFields({}).keywords.length,0);
  const config=topicFromFields({keywords:'具身智能\nrobot',aliases:'具身智能=embodied AI|embodied intelligence',exclusions:'crypto',match:'all',days:'14'});
  assert.equal(config.match,'all');assert.equal(config.lookback_days,14);assert.deepEqual(config.english_aliases['具身智能'],['embodied AI','embodied intelligence']);
  assert.match(topicLabel(config,'zh-TW'),/關鍵字專題/);assert.match(topicLabel(config,'en'),/Topic edition/);
});
test('query injection, controls, malformed aliases and unknown fields rejected',()=>{
  for(const value of [{keywords:['AI\" OR evil']},{keywords:['ＡＩ＂']},{keywords:['AI\u0000']},{keywords:['<script>']},{lookback_days:true},{lookback_days:31},{schema_version:true},{keywords:['AI'],english_aliases:{missing:['robot']}},{keywords:['AI'],english_aliases:{AI:['中文']}},{toString:'bad'}])assert.throws(()=>validateTopic(value));
  assert.throws(()=>topicFromFields({keywords:'AI',aliases:'AI robot'}));assert.throws(()=>topicFromFields({keywords:'AI',aliases:'AI=robot\nAI=tool'}));
});
test('no prototype field or implicit alias affects matching',()=>{
  const config=topicFromFields({keywords:'__proto__',aliases:'__proto__=AI'});assert.equal(matchTopic('AI','',config).eligible,true);assert.equal({}.polluted,undefined);
});

test('topic editor uses text-only preview and never performs a server save',async()=>{
  const {bindTopicEditor}=await import('../../daily/topic-config.mjs');
  const handlers={};const elements=Object.fromEntries(Object.entries({keywords:'AI',aliases:'',exclusions:'',match:'any',days:'7'}).map(([k,value])=>[k,{value}]));
  const form={elements,addEventListener:(name,fn)=>handlers[name]=fn};
  const preview={textContent:''},status={textContent:''};
  const document={querySelector:selector=>({'#topic-settings-form':form,'#topic-config-preview':preview,'#topic-settings-status':status})[selector]};
  const editor=bindTopicEditor(document);assert.match(preview.textContent,/"AI"/);assert.match(status.textContent,/Local configuration/);
  elements.keywords.value='<script>bad</script>';handlers.input();assert.equal(preview.textContent,'');assert.match(status.textContent,/literal/);
  editor.setLocale('zh-TW');assert.match(status.textContent,/設定無效/);assert.doesNotMatch(status.textContent,/Invalid/);assert.equal(elements.keywords.value,'<script>bad</script>');
  elements.keywords.value='具身智能';elements.aliases.value='具身智能=embodied AI';handlers.input();assert.match(preview.textContent,/embodied AI/);
  assert.equal(status.textContent,'僅在本頁預覽設定');editor.setLocale('en');assert.equal(status.textContent,'Local configuration preview only');
  assert.equal(Object.hasOwn(preview,'innerHTML'),false);assert.equal(Object.hasOwn(status,'innerHTML'),false);
});
