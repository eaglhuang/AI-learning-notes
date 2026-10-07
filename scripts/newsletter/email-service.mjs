/** Optional server-side email adapter. Never import this file into the website.
 * Deploy only after approving a provider, sender, privacy notice and abuse control.
 * Production must inject a durable rate limiter; credentials belong in server secrets.
 */
import {createHash} from 'node:crypto';
import {validateTopicEdition,topicLabel} from '../../daily/topic-config.mjs';
import {safeSummarySource} from '../../daily/issue-ui.mjs';
import contract from '../../daily/data/contract.json' with {type:'json'};

const HTTPS = value => { try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password; } catch { return false; } };
const locales = contract.locales;
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const positiveId = value => Number.isSafeInteger(value) && value > 0;
export const summaryContentDigest = (item,date) => createHash('sha256').update(JSON.stringify([
  date,item.id??null,item.source_url??null,item.summary_sources??[],
  ...locales.flatMap(locale=>['title','summary','takeaway','caveat'].map(field=>item[locale]?.[field]??null))
])).digest('hex');
const validSummarySources = sources => Array.isArray(sources) && sources.length>=1 && sources.length<=8
  && new Set(sources).size===sources.length && sources.every(value=>Boolean(safeSummarySource(value)));

export function editionToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en', {timeZone:'Asia/Taipei', year:'numeric', month:'2-digit', day:'2-digit'}).formatToParts(now);
  const part = name => parts.find(p=>p.type===name).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}

export function validateEmailEdition(issue, today = editionToday()) {
  const errors=[];
  const realDate=value => typeof value==='string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value+'T00:00:00Z')) && new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
  const nonempty=value => typeof value==='string' && Boolean(value.trim());
  if (!issue || typeof issue!=='object' || Array.isArray(issue)) return ['edition must be an object'];
  if (issue.schema_version!==contract.schema_version || issue.reviewed!==true || issue.synthetic!==false) errors.push('reviewed production edition required');
  if (!realDate(issue.date) || !realDate(issue.reviewed_on) || issue.date>today || issue.reviewed_on>today) errors.push('valid non-future edition and review dates required');
  for (const field of contract.issue_text_fields) for (const locale of locales) if (!nonempty(issue[field]?.[locale])) errors.push(`${field}.${locale} required`);
  if (!Array.isArray(issue.items)) return [...errors,'items must be an array'];
  if (issue.items.length<contract.min_items || issue.items.length>contract.max_items) errors.push('invalid edition size');
  const ids=new Set(),urls=new Set();
  for (const item of issue.items) {
    if (!item || typeof item!=='object') { errors.push('invalid item');continue; }
    if (typeof item.id!=='string' || !/^[a-z0-9][a-z0-9-]{0,63}$/.test(item.id) || ids.has(item.id)) errors.push('invalid or duplicate item id');
    ids.add(item.id);
    if (!contract.categories.includes(item.category) || !nonempty(item.source)) errors.push('item category/source required');
    if (!realDate(item.published_date) || item.published_date>issue.date) errors.push('invalid item publication date');
    try {
      if (typeof item.source_url!=='string' || !item.source_url.isWellFormed() || /\s|[\x00-\x1f\x7f\\]/.test(item.source_url)) throw Error();
      const url=new URL(item.source_url);
      if (url.protocol!=='https:' || url.port || url.username || url.password || !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(url.hostname) || url.hostname.includes('..')) throw Error();
      url.hash='';const key=url.toString();if(urls.has(key))errors.push('duplicate source URL');urls.add(key);
    } catch { errors.push('safe HTTPS source URL required'); }
    for (const locale of locales) for (const [field,max] of Object.entries(contract.item_text_limits)) if (!nonempty(item[locale]?.[field]) || [...item[locale][field]].length>max) errors.push(`${locale}.${field} missing or too long`);
    if (item.summary_sources!==undefined && !validSummarySources(item.summary_sources)) errors.push('summary_sources must contain 1–8 unique safe HTTPS source URLs');
    const policy=realDate(issue.date) ? contract.summary_policies
      .filter(p=>p.effective_from<=issue.date)
      .reduce((latest,p)=>!latest || p.effective_from>latest.effective_from ? p : latest,null) : null;
    if (policy) {
      const value=item[policy.locale]?.summary;
      // Unicode White_Space, exactly the same set used by edition.py.
      const length=typeof value==='string'?[...value.replace(/[\u0009-\u000d\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu,'')].length:0;
      const exception=item.summary_length_exception;
      if(exception!==undefined && exception!==null){
        const keys=['schema_version','reason','reviewed','reviewed_on','actual_characters','content_sha256'];
        const valid=exception&&typeof exception==='object'&&!Array.isArray(exception)
          && Object.keys(exception).length===keys.length&&keys.every(k=>Object.hasOwn(exception,k))
          && exception.schema_version===1&&policy.short_summary_exceptions?.includes(exception.reason)
          && exception.reviewed===true&&Number.isInteger(exception.actual_characters)&&exception.actual_characters===length
          && length>0&&length<policy.min_characters&&validSummarySources(item.summary_sources)
          && realDate(exception.reviewed_on)&&exception.reviewed_on>=issue.date&&exception.reviewed_on<=today
          && locales.every(locale=>['title','summary','takeaway','caveat'].every(field=>typeof item[locale]?.[field]==='string'&&item[locale][field].isWellFormed()))
          && exception.content_sha256===summaryContentDigest(item,issue.date);
        if(!valid)errors.push('short summary exception requires a current, content-bound source review');
      }else if (length<policy.min_characters || length>policy.max_characters) errors.push(`Traditional Chinese summary must contain ${policy.min_characters}–${policy.max_characters} non-whitespace characters (target ${policy.target_characters})`);
    } else if(item.summary_length_exception!=null) errors.push('short summary exceptions are unavailable for this edition date');
  }
  return [...errors,...validateTopicEdition(issue)];
}

export function createSubscriptionHandler({origin, provider, rateLimiter} = {}) {
  return async request => {
    const cors = {'Content-Type':'application/json','Cache-Control':'no-store','Vary':'Origin'};
    const respond = (status, body, allowed = false) => new Response(JSON.stringify(body), {status,headers:{...cors,...(allowed ? {'Access-Control-Allow-Origin':origin} : {})}});
    if (!HTTPS(origin) || new URL(origin).origin !== origin || !provider || !rateLimiter) return respond(503,{status:'unavailable'});
    if (request.headers.get('Origin') !== origin) return respond(403,{status:'forbidden'});
    if (request.method === 'OPTIONS') return new Response(null,{status:204,headers:{...cors,'Access-Control-Allow-Origin':origin,'Access-Control-Allow-Methods':'POST','Access-Control-Allow-Headers':'Content-Type','Access-Control-Max-Age':'600'}});
    if (request.method !== 'POST') return respond(405,{status:'method_not_allowed'},true);
    if (!request.headers.get('Content-Type')?.toLowerCase().startsWith('application/json')) return respond(415,{status:'invalid_content_type'},true);
    let input;
    try {
      const reader = request.body?.getReader(); if (!reader) return respond(400,{status:'invalid_request'},true);
      let size = 0; const chunks = [];
      while (true) { const {value,done} = await reader.read(); if (done) break; size += value.length; if (size > 2048) { await reader.cancel(); return respond(413,{status:'too_large'},true); } chunks.push(value); }
      const bytes = new Uint8Array(size); let offset = 0; chunks.forEach(chunk => {bytes.set(chunk,offset);offset+=chunk.length;});
      input = JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    } catch { return respond(400,{status:'invalid_request'},true); }
    if (!input || typeof input !== 'object' || typeof input.email !== 'string' || input.email.length > 254 || !/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(input.email) || !locales.includes(input.locale) || input.consent !== true || input.website) return respond(400,{status:'invalid_request'},true);
    // The limiter receives a keyed token supplied by the deployment, not an email
    // copied into logs. It must enforce both network-level and recipient-level limits.
    try {
      if (!await rateLimiter.allow({request,email:input.email.trim()})) return respond(429,{status:'rate_limited'},true);
      await provider.requestDoubleOptIn({email:input.email.trim(),locale:input.locale});
      return respond(202,{status:'confirmation_requested'},true);
    } catch { return respond(503,{status:'unavailable'},true); }
  };
}

export class BrevoProvider {
  constructor({apiKey, templateIds, listIds, redirectUrl, sender, footer}, fetcher = fetch) {
    if (!apiKey || !HTTPS(redirectUrl) || !locales.every(l => positiveId(templateIds?.[l]) && positiveId(listIds?.[l]))) throw new Error('Server-side Brevo DOI configuration is incomplete');
    this.config = {apiKey,templateIds,listIds,redirectUrl,sender,footer}; this.fetcher = fetcher;
  }
  async request(path, body) {
    const result = await this.fetcher('https://api.brevo.com/v3'+path,{method:'POST',redirect:'error',headers:{'api-key':this.config.apiKey,'Content-Type':'application/json','Accept':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
    if (!result.ok) throw new Error('Email provider did not accept the request'); // Never expose PII/provider response to browsers or logs.
    return result.status === 204 ? null : result.json();
  }
  requestDoubleOptIn({email,locale}) {
    if (!locales.includes(locale)) throw new Error('Unsupported email language');
    return this.request('/contacts/doubleOptinConfirmation',{email,includeListIds:[this.config.listIds[locale]],templateId:this.config.templateIds[locale],redirectionUrl:this.config.redirectUrl});
  }
  async createCampaign({subject,html,locale,date}) {
    if (!locales.includes(locale) || !this.config.sender?.email || !this.config.sender?.name || !this.config.footer) throw new Error('Approved sender and footer are required');
    const htmlContent=html.replace('<!--PROVIDER_FOOTER-->',`<footer><p>${escape(this.config.footer)}</p><p><a href="{{ unsubscribe }}">${locale==='en'?'Unsubscribe':'取消訂閱'}</a></p></footer>`);
    const result=await this.request('/emailCampaigns',{name:`AI Daily ${date} ${locale}`,type:'classic',sender:this.config.sender,subject,htmlContent,recipients:{listIds:[this.config.listIds[locale]]},mirrorActive:true});
    if (!positiveId(result?.id)) throw new Error('Campaign identifier was not confirmed');
    return result.id;
  }
  sendCampaign(id) {
    if (!positiveId(id)) throw new Error('Invalid campaign identifier');
    return this.request(`/emailCampaigns/${id}/sendNow`,{});
  }
}

export function renderEmail(issue,locale,siteUrl) {
  if (!locales.includes(locale) || validateEmailEdition(issue).length || !HTTPS(siteUrl)) throw new Error('Valid reviewed production edition and HTTPS site URL required');
  const canonical=siteUrl.replace(/\/$/,'')+'/daily/'+issue.date+(locale==='en'?'/en/':'/');
  for (const item of issue.items) if (!HTTPS(item.source_url) || !item[locale]?.title || !item[locale]?.summary) throw new Error('Incomplete or unsafe email content');
  const subject=`${issue.date} · ${issue.title[locale]}`;
  const shortNote=item=>item.summary_length_exception ? (locale==='en'?'Shorter summary: limited to verified source material and permitted condensation.':'本則採較短摘要：以已核對的原文內容與摘要使用範圍為限。') : '';
  const sourceLinks=item=>(item.summary_sources??[]).map(url=>`<li><a href="${escape(url)}">${escape(url)}</a></li>`).join('');
  const items=issue.items.map(item=>`<tr><td style="padding:22px 28px;border-bottom:1px solid #cdd0bb"><h2 style="font-size:20px;color:#17493f">${escape(item[locale].title)}</h2><p>${escape(item[locale].summary)}</p>${shortNote(item)?`<p>${escape(shortNote(item))}</p>`:''}${sourceLinks(item)?`<p>${locale==='en'?'Summary sources':'摘要來源'}</p><ul>${sourceLinks(item)}</ul>`:''}<p><a href="${escape(item.source_url)}">${escape(item.source)} ↗</a></p></td></tr>`).join('');
  const html=`<!doctype html><html lang="${locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(subject)}</title></head><body style="margin:0;background:#f6f0df;color:#1c211c;font:16px/1.7 Georgia,serif"><table role="presentation" style="max-width:640px;width:100%;margin:auto;background:#fcf8ee"><tr><td style="padding:28px;background:#17493f;color:#fcf8ee"><p>ATOMIC AI DAILY / ${issue.date}</p><p>${escape(topicLabel(issue.topic,locale))}</p><h1 style="font-size:28px">${escape(issue.title[locale])}</h1><p>${escape(issue.coverage[locale])}</p></td></tr>${items}<tr><td style="padding:28px"><a href="${escape(canonical)}">${locale==='en'?'Read the full edition':'閱讀完整日報'} ↗</a><p>${escape(issue.editorial_note[locale])}</p><!--PROVIDER_FOOTER--></td></tr></table></body></html>\n`;
  const text=[subject,topicLabel(issue.topic,locale),issue.coverage[locale],...issue.items.map(i=>`${i[locale].title}\n${i[locale].summary}\n${shortNote(i)}\n${[i.source_url,...(i.summary_sources??[])].join('\n')}`),canonical,'Unsubscribe: supplied by the approved email provider'].join('\n\n')+'\n';
  return {subject,html,text,canonical};
}

/** ledger.claim(key) must be an atomic durable create-if-absent operation.
 * Any uncertain network outcome stays reserved for manual reconciliation.
 * No automatic retry can accidentally resend a campaign.
 */
export async function deliverEdition({issue,locale,siteUrl,provider,ledger,approval,recipientCount,maxRecipients}) {
  const email=renderEmail(issue,locale,siteUrl);
  const digest=createHash('sha256').update(email.html).digest('hex');
  if (!approval) return {status:'preview',...email,digest};
  if (approval.date!==issue.date || approval.locale!==locale || approval.digest!==digest || !provider || !ledger || !Number.isSafeInteger(recipientCount) || recipientCount<1 || !Number.isSafeInteger(maxRecipients) || maxRecipients<1 || recipientCount>maxRecipients) throw new Error('Exact edition approval, durable ledger, and recipient capacity required');
  // Edition+language, not digest: a corrected issue must not silently resend.
  const key=`${issue.date}:${locale}`;
  if (!await ledger.claim(key,{digest,state:'reserved'})) return {status:'already_reserved'};
  try {
    const id=await provider.createCampaign({...email,locale,date:issue.date});
    await ledger.update(key,{digest,campaignId:id,state:'send_requested'});
    await provider.sendCampaign(id);
    await ledger.update(key,{digest,campaignId:id,state:'accepted'});
    return {status:'accepted',campaignId:id};
  } catch {
    await ledger.update(key,{digest,state:'uncertain'});
    throw new Error('Delivery outcome uncertain; inspect provider and ledger before retrying');
  }
}
