/** Server-only, opt-in Kit V4 readiness and draft adapter.
 * No credentials are loaded, no transport is selected, and no sends are exposed.
 * Hosted-form handoff does not subscribe anyone or prove double opt-in remotely.
 */
import {createHash} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
import {renderEmail} from './email-service.mjs';
import {validTimestamp} from '../../daily/topic-config.mjs';

const LOCALES = ['zh-TW', 'en'];
const ENDPOINT = 'https://api.kit.com/v4/broadcasts';
const MAX_RESPONSE = 1024 * 1024;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const id = value => Number.isSafeInteger(value) && value > 0;
const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
  && !Number.isNaN(Date.parse(value + 'T00:00:00Z'))
  && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
const text = value => typeof value === 'string' && Boolean(value.trim()) && !/[\x00-\x1f\x7f{}]/.test(value);
const email = value => text(value) && value.length <= 254 && /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(value);
const sha = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

function safeUrl(value, hosted = false) {
  if (typeof value !== 'string' || /[\s\\{}\x00-\x1f\x7f]/.test(value)) return false;
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password || u.port || u.search || u.hash
        || !/^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/.test(u.hostname) || u.hostname.includes('..')) return false;
    if (!hosted) return true;
    // Only first-party hosted forms in this increment; custom domains need review.
    return /^[a-z0-9-]+\.(?:kit\.com|ck\.page)$/.test(u.hostname)
      && !['api', 'app', 'www', 'help', 'developers'].includes(u.hostname.split('.')[0]);
  } catch { return false; }
}

function keys(value, allowed, path, errors) {
  if (!object(value)) { errors.push(`${path}: object required`); return false; }
  if (Object.keys(value).some(k => !allowed.includes(k))) errors.push(`${path}: unknown fields are not allowed`);
  if (allowed.some(k => !Object.hasOwn(value, k))) errors.push(`${path}: required fields missing`);
  return true;
}

function verification(value, expected, today) {
  return object(value) && Object.keys(value).length === Object.keys(expected).length + 1
    && Object.entries(expected).every(([key, item]) => value[key] === item)
    && date(value.checked_on) && value.checked_on <= today;
}

/** Reports local configuration only. Attestations are operator assertions, not API checks. */
export function kitReadiness(config, today = new Date().toISOString().slice(0, 10)) {
  const errors = [], drafts = [], subscriptions = [];
  if (!date(today)) throw new Error('Valid readiness date required');
  if (!keys(config, ['schema_version', 'provider', 'drafts_enabled', 'subscriptions_enabled',
    'site_url', 'sender_email', 'sender_verification', 'locales'], 'config', errors)) {
    return {status: 'invalid', errors, drafts: {enabled: false, ready: false}, subscriptions: {enabled: false, ready: false}};
  }
  if (config.schema_version !== 1 || config.provider !== 'kit') errors.push('Kit schema version 1 required');
  for (const flag of ['drafts_enabled', 'subscriptions_enabled']) if (typeof config[flag] !== 'boolean') errors.push(`${flag}: boolean required`);
  if (!safeUrl(config.site_url)) errors.push('site_url: safe HTTPS URL without query or fragment required');
  if (config.sender_email !== null && !email(config.sender_email)) errors.push('sender_email: invalid');
  if (!email(config.sender_email)) drafts.push('verified sender email required');
  if (config.sender_verification !== null) keys(config.sender_verification, ['email_address', 'checked_on'], 'sender_verification', errors);
  if (!verification(config.sender_verification, {email_address: config.sender_email}, today)) drafts.push('sender verification required');
  if (keys(config.locales, LOCALES, 'locales', errors)) {
    for (const locale of LOCALES) {
      const c = config.locales[locale];
      if (!keys(c, ['form_id', 'hosted_url', 'segment_id', 'email_template_id', 'template_type',
        'doi_verification', 'audience_verification', 'template_verification'], `locales.${locale}`, errors)) continue;
      for (const field of ['form_id', 'segment_id', 'email_template_id']) if (c[field] !== null && !id(c[field])) errors.push(`${locale}.${field}: positive integer or null required`);
      if (c.hosted_url !== null && !safeUrl(c.hosted_url, true)) errors.push(`${locale}.hosted_url: approved first-party HTTPS hosted form required`);
      if (c.template_type !== 'classic') errors.push(`${locale}.template_type: classic required`);
      for (const [field, fields] of Object.entries({
        doi_verification: ['locale', 'form_id', 'hosted_url', 'confirmation_email_enabled', 'auto_confirm', 'consent_notice_verified', 'checked_on'],
        audience_verification: ['locale', 'segment_id', 'confirmed_only', 'exclusive_language', 'checked_on'],
        template_verification: ['locale', 'email_template_id', 'template_type', 'footer_verified', 'checked_on'],
      })) if (c[field] !== null) keys(c[field], fields, `${locale}.${field}`, errors);
      if (!id(c.form_id) || !safeUrl(c.hosted_url, true)) subscriptions.push(`${locale}: hosted form required`);
      if (!verification(c.doi_verification, {locale, form_id: c.form_id, hosted_url: c.hosted_url,
        confirmation_email_enabled: true, auto_confirm: false, consent_notice_verified: true}, today)) subscriptions.push(`${locale}: bound double-opt-in and consent verification required`);
      if (!id(c.segment_id)) drafts.push(`${locale}: segment required`);
      if (!verification(c.audience_verification, {locale, segment_id: c.segment_id,
        confirmed_only: true, exclusive_language: true}, today)) drafts.push(`${locale}: bound confirmed-only language audience verification required`);
      if (!id(c.email_template_id)) drafts.push(`${locale}: email template required`);
      if (!verification(c.template_verification, {locale, email_template_id: c.email_template_id,
        template_type: 'classic', footer_verified: true}, today)) drafts.push(`${locale}: bound template and footer verification required`);
    }
    const zh = config.locales['zh-TW'], en = config.locales.en;
    if (object(zh) && object(en)) {
      if (id(zh.form_id) && zh.form_id === en.form_id) subscriptions.push('language form IDs must differ');
      if (safeUrl(zh.hosted_url, true) && safeUrl(en.hosted_url, true)
          && new URL(zh.hosted_url).href === new URL(en.hosted_url).href) subscriptions.push('language hosted form URLs must differ');
      if (id(zh.segment_id) && zh.segment_id === en.segment_id) drafts.push('language segment IDs must differ');
    }
  }
  return {
    status: errors.length ? 'invalid' : 'local_configuration_only', errors,
    drafts: {enabled: config.drafts_enabled === true, ready: !errors.length && !drafts.length, missing: drafts},
    subscriptions: {enabled: config.subscriptions_enabled === true, ready: !errors.length && !subscriptions.length, missing: subscriptions},
    remote_verified: false,
  };
}

export function kitSubscriptionHandoff(config, locale) {
  if (!LOCALES.includes(locale)) throw new Error('Unsupported subscription language');
  const check = kitReadiness(config);
  if (check.errors.length) throw new Error('Invalid Kit configuration');
  if (!check.subscriptions.enabled) return {status: 'disabled'};
  if (!check.subscriptions.ready) throw new Error('Hosted form and double-opt-in verification required');
  return {status: 'hosted_form_handoff', locale, url: config.locales[locale].hosted_url,
    collects_email_here: false, subscription_confirmed: false};
}

function freeze(value) {
  if (object(value) || Array.isArray(value)) { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

/** Pure local rendering. This is not approval to create a draft at Kit. */
export function prepareKitDraft({config, issue, locale}) {
  const check = kitReadiness(config);
  if (!check.drafts.ready || !LOCALES.includes(locale)) throw new Error('Verified language-scoped Kit draft configuration required');
  const rendered = renderEmail(issue, locale, config.site_url);
  if (!text(rendered.subject) || !text(issue.coverage[locale])) throw new Error('Plain subject and preview text without Liquid or control characters required');
  // Neutralize Liquid from ALL untrusted rendered content, then insert only our
  // two documented provider variables. HTML escaping alone does not stop Liquid.
  // Classic templates own the outer HTML document. Extract only the body from
  // our trusted renderer and retain its inline styling on a fragment wrapper.
  const body = rendered.html.match(/<body style="([^"]*)">([\s\S]*)<\/body><\/html>\n$/);
  if (!body) throw new Error('Unsupported email renderer body structure');
  const fragment = `<div lang="${locale}" style="${body[1]}">${body[2]}</div>`;
  const safeHtml = fragment.replaceAll('{', '&#123;').replaceAll('}', '&#125;');
  const footer = `<footer><p>{{ address }}</p><p><a href="{{ unsubscribe_url }}">${locale === 'en' ? 'Unsubscribe' : '取消訂閱'}</a></p></footer>`;
  const c = config.locales[locale];
  const payload = {
    email_template_id: c.email_template_id, email_address: config.sender_email,
    content: safeHtml.replace('<!--PROVIDER_FOOTER-->', footer),
    description: `AI Daily ${issue.date} ${locale}`, public: false,
    // A display date required by Kit's schema, not a send or publication action.
    published_at: issue.date + 'T00:00:00Z', send_at: null,
    preview_text: issue.coverage[locale], subject: rendered.subject,
    subscriber_filter: [{all: [{type: 'segment', ids: [c.segment_id]}]}],
  };
  const binding = {action: 'create_kit_draft', date: issue.date, locale, payload};
  return freeze({status: 'local_preview', action: binding.action, date: issue.date, locale,
    digest: sha(binding), payload});
}

async function readResponse(response) {
  if (response.status !== 201 || !/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') || '')) throw new Error('Unexpected Kit response');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Missing Kit response');
  const chunks = []; let size = 0;
  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_RESPONSE) { await reader.cancel(); throw new Error('Oversized Kit response'); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
}

function verifyDraft(result, payload) {
  const b = result?.broadcast;
  const filter = b?.subscriber_filter;
  // Kit may echo unused groups as null. Any non-null extra targeting is refused.
  const expectedFilter = payload.subscriber_filter;
  const cleaned = Array.isArray(filter) && filter.map(group => object(group)
    ? Object.fromEntries(Object.entries(group).filter(([k, v]) => !(['any', 'none'].includes(k) && v === null))) : group);
  return id(b?.id) && b.status === 'draft' && b.public === false && b.send_at === null
    && b.public_url === null && b.email_address === payload.email_address
    && b.email_template?.id === payload.email_template_id && b.subject === payload.subject
    && b.preview_text === payload.preview_text && b.description === payload.description
    && validTimestamp(b.published_at) && Date.parse(b.published_at) === Date.parse(payload.published_at)
    && b.content === payload.content && isDeepStrictEqual(cleaned, expectedFilter);
}

/** The only network-capable entry. No default fetch, no automatic retries.
 * ledger.claim must atomically and durably reserve a key; update must persist it.
 * An approval authorizes ONE draft creation only, never a send or web publication.
 * Call only after separate owner approval of the actual service/account operation.
 */
export async function createKitDraft({config, issue, locale, approval, ledger, apiKey, fetcher}) {
  const check = kitReadiness(config);
  if (check.errors.length) throw new Error('Invalid Kit configuration');
  if (!check.drafts.enabled) return {status: 'disabled'};
  const prepared = prepareKitDraft({config, issue, locale});
  if (!approval) return prepared;
  if (!object(approval) || Object.keys(approval).length !== 4
      || !['action', 'date', 'locale', 'digest'].every(key => approval[key] === prepared[key])
      || typeof ledger?.claim !== 'function' || typeof ledger?.update !== 'function'
      || typeof fetcher !== 'function' || typeof apiKey !== 'string'
      || !/^[\x21-\x7e]{1,512}$/.test(apiKey)) throw new Error('Exact draft approval, durable ledger and explicit server transport required');
  const {date: issueDate, digest, payload} = prepared;
  const key = `kit-draft:${issueDate}:${locale}`;
  let claimed;
  try { claimed = await ledger.claim(key, {state: 'reserved', digest}); }
  catch { throw new Error('Draft reservation failed; no provider request was made'); }
  if (claimed !== true) return {status: 'already_reserved'};
  try {
    const response = await fetcher(ENDPOINT, {method: 'POST', redirect: 'error',
      headers: {'X-Kit-Api-Key': apiKey, 'Content-Type': 'application/json', Accept: 'application/json'},
      body: JSON.stringify(payload), signal: AbortSignal.timeout(15000)});
    const result = await readResponse(response);
    if (!verifyDraft(result, payload)) throw new Error('Draft state or scope unconfirmed');
    await ledger.update(key, {state: 'draft_created', digest, broadcast_id: result.broadcast.id});
    return {status: 'draft_created', broadcast_id: result.broadcast.id, date: issueDate, locale, digest};
  } catch {
    // Keep the original durable reservation even if updating diagnostics fails.
    try { await ledger.update(key, {state: 'uncertain', digest}); } catch { /* reserved */ }
    throw new Error('Kit draft outcome uncertain; reconcile provider and ledger before retrying');
  }
}
