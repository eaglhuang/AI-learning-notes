/** Topic configuration export and validation. This never searches or saves server settings. */
import casefold from './casefold.mjs';
const object = x => x && typeof x==='object' && !Array.isArray(x);
const space = /[\s\u001c-\u001f\u0085]+/gu;
export const fold = value => [...value.normalize('NFKC')].map(c=>casefold[c]??c.toLowerCase()).join('').replace(space,' ').trim();
const term = value => {
  if(typeof value!=='string' || /\p{C}/u.test(value))throw Error('Use visible keyword text / 請輸入可見的關鍵字');
  value=value.normalize('NFKC').replace(space,' ').trim();
  if(!value || [...value].length>80 || /["\\:()[\]{}<>]/u.test(value))throw Error('Use 1–80 literal characters without query operators / 請勿使用查詢運算子');
  return value;
};
const terms = values => {
  if(!Array.isArray(values)||values.length>8)throw Error('At most 8 keywords / 最多 8 個關鍵字');
  const result=[];for(const value of values){const text=term(value);if(!result.some(x=>fold(x)===fold(text)))result.push(text);}return result;
};
export function validateTopic(value={}) {
  const defaults={schema_version:1,keywords:[],english_aliases:{},match:'any',exclude_keywords:[],lookback_days:7};
  if(!object(value)||Object.keys(value).some(k=>!Object.hasOwn(defaults,k)))throw Error('Unknown topic fields / 主題設定欄位無效');
  const topic={...defaults,...value};
  if(topic.schema_version!==1 || !['any','all'].includes(topic.match) || !Number.isInteger(topic.lookback_days)||topic.lookback_days<1||topic.lookback_days>30)throw Error('Invalid topic version, match or lookback / 主題版本、比對或天數無效');
  topic.keywords=terms(topic.keywords);topic.exclude_keywords=terms(topic.exclude_keywords);
  if(!object(topic.english_aliases))throw Error('Invalid English aliases / 英文別名無效');
  const aliases=Object.create(null);for(const [key,list] of Object.entries(topic.english_aliases)){
    const known=topic.keywords.find(k=>fold(k)===fold(term(key)));
    if(!known||Object.hasOwn(aliases,known))throw Error('Alias must name a unique configured keyword / 別名需對應已設定的關鍵字');
    const values=terms(list);if(values.length>3||values.some(x=>/[^\x00-\x7f]/.test(x)||!/[a-z]/i.test(x)))throw Error('Up to 3 English aliases per keyword / 每個關鍵字最多 3 個英文別名');
    Object.defineProperty(aliases,known,{value:values,enumerable:true});
  }
  topic.english_aliases=aliases;
  if(!topic.keywords.length&&(Object.keys(aliases).length||topic.exclude_keywords.length))throw Error('Exclusions require keywords / 排除詞需要關鍵字');
  return topic;
}
export function matchTopic(title,excerpt,topic){
  const contains=(text,key)=>{
    key=fold(key);text=fold(text);
    const escaped=key.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    return new RegExp((/^[a-z0-9_]/.test(key)?'(?<![a-z0-9_])':'')+escaped+(/[a-z0-9_]$/.test(key)?'(?![a-z0-9_])':''),'u').test(text);
  };
  const matched_keywords=[],matched_terms=[];
  for(const key of topic.keywords){
    const found=[key,...(Object.hasOwn(topic.english_aliases,key)?topic.english_aliases[key]:[])].filter(term=>[title,excerpt].some(text=>contains(text,term)));
    if(found.length){matched_keywords.push(key);matched_terms.push(...found);}
  }
  const excluded_terms=topic.exclude_keywords.filter(key=>[title,excerpt].some(text=>contains(text,key)));
  return {eligible:!excluded_terms.length&&(topic.match==='all'?matched_keywords.length===topic.keywords.length:!topic.keywords.length||matched_keywords.length>0),matched_keywords,matched_terms:[...new Set(matched_terms)],excluded_terms};
}
export function validTimestamp(value){
  if(typeof value!=='string')return false;
  const m=/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if(!m)return false;
  const [year,month,day,hour,minute,second]=m.slice(1,7).map(Number);
  const leap=year%4===0&&(year%100!==0||year%400===0),days=[31,leap?29:28,31,30,31,30,31,31,30,31,30,31];
  return year>=1&&month>=1&&month<=12&&day>=1&&day<=days[month-1]&&hour<=23&&minute<=59&&second<=59&&(!m[7]||(Number(m[8])<=23&&Number(m[9])<=59))&&!Number.isNaN(Date.parse(value));
}
function validProvenance(record){
  if(!object(record)||!['rss','gdelt','arxiv'].includes(record.provider)||typeof record.query!=='string'||record.query.length>4000||!validTimestamp(record.retrieved_at))return false;
  try{
    if(typeof record.request_url!=='string'||/\s|[\x00-\x1f\x7f\\]/.test(record.request_url))return false;
    const u=new URL(record.request_url),hosts={gdelt:'api.gdeltproject.org',arxiv:'export.arxiv.org'};
    if(u.protocol!=='https:'||u.username||u.password||u.port||!/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(u.hostname)||u.hostname.includes('..')||(hosts[record.provider]&&u.hostname!==hosts[record.provider]))return false;
    if(record.provider==='rss')return record.query==='';
    const field=record.provider==='gdelt'?'query':'search_query',path=record.provider==='gdelt'?'/api/v2/doc/doc':'/api/query';
    return Boolean(record.query)&&u.pathname===path&&JSON.stringify(u.searchParams.getAll(field))===JSON.stringify([record.query]);
  }catch{return false;}
}
export function validateTopicEdition(issue){
  if(!Object.hasOwn(issue,'topic'))return [];
  let topic;try{topic=validateTopic(issue.topic);}catch(error){return [error.message];}
  if(!topic.keywords.length)return [];
  const errors=[],discovery=issue.discovery;
  if(!object(discovery))return ['topic discovery metadata required'];
  if(!['completed','partial'].includes(discovery.search_status)||!Array.isArray(discovery.searches)||!discovery.searches.some(q=>object(q)&&q.status==='ok'&&['gdelt','arxiv'].includes(q.provider)))errors.push('successful topic search receipt required');
  if(discovery.search_status==='completed'&&(discovery.failures?.length||discovery.coverage_warnings?.length||(Array.isArray(discovery.searches)&&discovery.searches.some(q=>q?.status!=='ok'))))errors.push('completed search cannot conceal failures or warnings');
  if(Array.isArray(discovery.searches)&&discovery.searches.some(q=>!validProvenance(q)))errors.push('malformed search receipt');
  if(discovery.search_status==='partial'&&discovery.limitations_acknowledged!==true)errors.push('partial-search limitations must be acknowledged');
  if(!validTimestamp(discovery.collected_at)||discovery.collected_at.slice(0,10)>issue.date)errors.push('valid discovery timestamp required');
  for(const item of issue.items??[]){
    if(!object(item))continue;
    const evidence=item.topic_evidence;
    if(!object(evidence)||typeof evidence.source_title!=='string'||!evidence.source_title.trim()||[...evidence.source_title].length>1800||typeof evidence.source_excerpt!=='string'||[...evidence.source_excerpt].length>1800){errors.push('bounded topic source evidence required');continue;}
    const match=matchTopic(evidence.source_title,evidence.source_excerpt,topic);
    if(!match.eligible||['matched_keywords','matched_terms'].some(k=>JSON.stringify(evidence[k])!==JSON.stringify(match[k])))errors.push('topic source matches do not verify');
    if(item.date_verification_required===true)errors.push('publication date must be verified');
    if(Date.parse(item.published_date+'T00:00:00Z')<Date.parse(issue.date+'T00:00:00Z')-topic.lookback_days*86400000)errors.push('publication date outside topic lookback');
    if(!Array.isArray(evidence.provenance)||!evidence.provenance.length||evidence.provenance.length>16){errors.push('discovery provenance required');continue;}
    for(const record of evidence.provenance)if(!validProvenance(record))errors.push('safe discovery provenance required');
  }
  return errors;
}
export function topicLabel(topic,locale){
  return topic?.keywords?.length ? (locale==='en'?'Topic edition: ':'關鍵字專題：')+topic.keywords.join(' / ')+(topic.match==='all'?' · AND':' · OR') : (locale==='en'?'General AI edition':'一般 AI 選讀');
}
export function topicFromFields({keywords='',aliases='',exclusions='',match='any',days='7'}){
  const split=value=>value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean), map=Object.create(null);
  for(const line of split(aliases)){
    const at=line.indexOf('=');if(at<1)throw Error('Alias format: keyword=English|English / 別名格式：關鍵字=英文|英文');
    const key=line.slice(0,at).trim();if(Object.hasOwn(map,key))throw Error('Duplicate alias row / 別名列重複');
    Object.defineProperty(map,key,{value:line.slice(at+1).split('|').map(x=>x.trim()),enumerable:true});
  }
  return validateTopic({schema_version:1,keywords:split(keywords),english_aliases:map,match,exclude_keywords:split(exclusions),lookback_days:Number(days)});
}
export function bindTopicEditor(document, initialLocale='en'){
  const form=document.querySelector('#topic-settings-form');if(!form)return;
  const preview=document.querySelector('#topic-config-preview'),status=document.querySelector('#topic-settings-status');
  const read=()=>topicFromFields({keywords:form.elements.keywords.value,aliases:form.elements.aliases.value,exclusions:form.elements.exclusions.value,match:form.elements.match.value,days:form.elements.days.value});
  let locale=initialLocale==='zh-TW'?'zh-TW':'en',state='preview';
  const messages={
    preview:{'zh-TW':'僅在本頁預覽設定','en':'Local configuration preview only'},
    exported:{'zh-TW':'已匯出設定，需執行收集程式才會套用','en':'Configuration exported; run the collector to apply'},
    invalid:{'zh-TW':'設定無效，請檢查關鍵字、別名與回溯天數。關鍵字只能使用一般文字。','en':'Invalid configuration. Check literal keywords, aliases and lookback days.'}
  };
  const renderStatus=()=>{status.textContent=messages[state][locale];};
  const show=()=>{try{const topic=read();preview.textContent=JSON.stringify(topic,null,2);state='preview';renderStatus();return topic;}catch{preview.textContent='';state='invalid';renderStatus();return null;}};
  form.addEventListener('submit',event=>{event.preventDefault();const topic=show();if(!topic)return;const url=URL.createObjectURL(new Blob([JSON.stringify(topic,null,2)+'\n'],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='topics.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);state='exported';renderStatus();});
  form.addEventListener('input',show);
  form.addEventListener('reset',()=>setTimeout(show,0));
  show();
  return {setLocale(next){locale=next==='zh-TW'?'zh-TW':'en';renderStatus();}};
}
