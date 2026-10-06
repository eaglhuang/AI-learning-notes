import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile, mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {kitReadiness, kitSubscriptionHandoff, prepareKitDraft, createKitDraft} from '../../scripts/newsletter/kit-service.mjs';

const example = JSON.parse(await readFile(new URL('../../newsletter/examples/kit-config.example.json', import.meta.url), 'utf8'));
const issue = JSON.parse(await readFile(new URL('../../daily/data/issues/2026-10-04.json', import.meta.url), 'utf8'));
const today = '2026-10-05';
function configured() {
  const c = structuredClone(example);
  c.drafts_enabled = c.subscriptions_enabled = true;
  c.sender_email = 'newsletter@example.com';
  c.sender_verification = {email_address: c.sender_email, checked_on: today};
  for (const [index, locale] of ['zh-TW', 'en'].entries()) {
    const l = c.locales[locale];
    l.form_id = index + 1; l.hosted_url = `https://example.kit.com/${locale}`;
    l.segment_id = index + 11; l.email_template_id = index + 21;
    l.doi_verification = {locale, form_id: l.form_id, hosted_url: l.hosted_url,
      confirmation_email_enabled: true, auto_confirm: false, consent_notice_verified: true, checked_on: today};
    l.audience_verification = {locale, segment_id: l.segment_id, confirmed_only: true,
      exclusive_language: true, checked_on: today};
    l.template_verification = {locale, email_template_id: l.email_template_id,
      template_type: 'classic', footer_verified: true, checked_on: today};
  }
  return c;
}
function setup() {
  const config = configured(), states = [], reservations = new Set();
  const ledger = {
    claim: async (key, value) => { if (reservations.has(key)) return false; reservations.add(key); states.push(value); return true; },
    update: async (key, value) => { states.push(value); },
  };
  const args = {config, issue: structuredClone(issue), locale: 'en', ledger, apiKey: 'fake-unit-key'};
  const p = prepareKitDraft(args);
  args.approval = Object.fromEntries(['action', 'date', 'locale', 'digest'].map(k => [k, p[k]]));
  return {args, states, reservations};
}
function reply(payload, mutate = () => {}) {
  const b = {id: 71, ...payload, status: 'draft', public_url: null, email_template: {id: payload.email_template_id}};
  mutate(b);
  return new Response(JSON.stringify({broadcast: b}), {status: 201, headers: {'Content-Type': 'application/json'}});
}

test('example is valid, disabled, unconfigured, and never performs network work', async () => {
  const r = kitReadiness(example, today);
  assert.equal(r.status, 'local_configuration_only'); assert.equal(r.remote_verified, false);
  assert.equal(r.drafts.ready, false); assert.equal(r.subscriptions.ready, false);
  assert.deepEqual(kitSubscriptionHandoff(example, 'en'), {status: 'disabled'});
  assert.deepEqual(await createKitDraft({config: example, fetcher: () => assert.fail()}), {status: 'disabled'});
});

test('readiness separates local assertions from live verification', () => {
  const r = kitReadiness(configured(), today);
  assert.deepEqual(r.errors, []); assert.equal(r.drafts.ready, true); assert.equal(r.subscriptions.ready, true);
  assert.equal(r.remote_verified, false);
});

test('strict schema rejects unknown fields, unsafe URLs, secrets, and malformed IDs', () => {
  for (const change of [c => c.api_key = 'private', c => c.provider = 'other', c => c.drafts_enabled = 'yes',
    c => c.locales.fr = {}, c => c.locales.en.segment_id = 0, c => c.locales.en.form_id = '1',
    c => c.locales.en.extra = 'private', c => c.site_url = 'https://example.com?tracking=email',
    c => c.site_url = 'https://user:password@example.com', c => c.site_url = 'javascript:alert(1)',
    c => c.locales.en.hosted_url = 'https://evil.test/form', c => c.locales.en.hosted_url = 'https://api.kit.com/form',
    c => c.locales.en.hosted_url = 'https://example.kit.com.evil.test/form', c => c.locales.en.hosted_url = 'https://example.ck.page/form?email=private',
    c => c.locales.en.hosted_url = 'https://example.kit.com\\@evil.test/', c => c.sender_email = 'a\nb@example.com',
    c => c.locales.en.template_type = 'starting_point', c => delete c.locales.en.form_id]) {
    const c = configured(); change(c); const r = kitReadiness(c, today);
    assert.ok(r.errors.length); assert.equal(r.drafts.ready, false);
    assert.throws(() => kitSubscriptionHandoff(c, 'en'));
  }
  assert.equal(kitReadiness(null).status, 'invalid');
});

test('hosted subscription handoff requires bound DOI, consent, dates and distinct language forms', () => {
  for (const change of [c => c.locales.en.doi_verification = null,
    c => c.locales.en.doi_verification.auto_confirm = true,
    c => c.locales.en.doi_verification.confirmation_email_enabled = false,
    c => c.locales.en.doi_verification.consent_notice_verified = false,
    c => c.locales.en.doi_verification.locale = 'zh-TW',
    c => c.locales.en.doi_verification.form_id = 999,
    c => c.locales.en.doi_verification.hosted_url += '/other',
    c => c.locales.en.doi_verification.checked_on = '2026-02-30',
    c => c.locales.en.doi_verification.checked_on = '2999-01-01',
    c => c.locales.en.form_id = c.locales['zh-TW'].form_id,
    c => c.locales.en.hosted_url = c.locales['zh-TW'].hosted_url]) {
    const c = configured(); change(c); assert.equal(kitReadiness(c, today).subscriptions.ready, false);
    assert.throws(() => kitSubscriptionHandoff(c, 'en'));
  }
  const result = kitSubscriptionHandoff(configured(), 'en');
  assert.equal(result.status, 'hosted_form_handoff'); assert.equal(result.url, 'https://example.kit.com/en');
  assert.equal(result.collects_email_here, false); assert.equal(result.subscription_confirmed, false);
  assert.throws(() => kitSubscriptionHandoff(configured(), 'fr'));
});

test('draft requires verified sender, template and exclusive confirmed language audience', () => {
  for (const change of [c => c.sender_verification = null, c => c.sender_verification.email_address = 'other@example.com',
    c => c.locales.en.segment_id = null, c => c.locales.en.segment_id = c.locales['zh-TW'].segment_id,
    c => c.locales.en.audience_verification.confirmed_only = false,
    c => c.locales.en.audience_verification.exclusive_language = false,
    c => c.locales.en.audience_verification.locale = 'zh-TW',
    c => c.locales.en.audience_verification.checked_on = '2026-02-30',
    c => c.locales.en.template_verification.email_template_id = 100,
    c => c.locales.en.template_verification.footer_verified = false]) {
    const c = configured(); change(c); assert.equal(kitReadiness(c, today).drafts.ready, false);
    assert.throws(() => prepareKitDraft({config: c, issue, locale: 'en'}));
  }
});

test('language form separation compares canonical URL destinations', () => {
  for (const alias of ['https://EXAMPLE.kit.com/form', 'https://example.kit.com:443/form',
    'https://example.kit.com/en/../form', 'https://example.kit.com/en/%2e%2e/form']) {
    const c = configured();
    c.locales['zh-TW'].hosted_url = 'https://example.kit.com/form';
    c.locales['zh-TW'].doi_verification.hosted_url = c.locales['zh-TW'].hosted_url;
    c.locales.en.hosted_url = alias; c.locales.en.doi_verification.hosted_url = alias;
    const r = kitReadiness(c, today);
    assert.equal(r.subscriptions.ready, false); assert.ok(r.subscriptions.missing.includes('language hosted form URLs must differ'));
    assert.throws(() => kitSubscriptionHandoff(c, 'en'));
  }
});

test('pure preview binds every payload field and never schedules or defaults to all subscribers', () => {
  const c = configured();
  for (const [index, locale] of ['zh-TW', 'en'].entries()) {
    const p = prepareKitDraft({config: c, issue, locale});
    assert.equal(p.status, 'local_preview'); assert.equal(p.payload.send_at, null); assert.equal(p.payload.public, false);
    assert.deepEqual(p.payload.subscriber_filter, [{all: [{type: 'segment', ids: [index + 11]}]}]);
    assert.equal(p.payload.email_address, c.sender_email);
    assert.equal(p.payload.email_template_id, index + 21);
    assert.ok(!/<!doctype|<html|<head|<body|<\/body|<\/html/i.test(p.payload.content));
    assert.ok(p.payload.content.startsWith(`<div lang="${locale}" style="`));
    assert.ok(p.payload.content.includes('<table role="presentation"'));
    assert.throws(() => p.payload.subscriber_filter[0].all[0].ids.push(99), TypeError);
    assert.throws(() => p.payload.public = true, TypeError);
  }
});

test('only reviewed production bilingual editions can reach preview', () => {
  for (const change of [i => i.reviewed = false, i => i.synthetic = true, i => i.items = [],
    i => delete i.items[0]['zh-TW'], i => i.items[0].source_url = 'javascript:alert(1)']) {
    const i = structuredClone(issue); change(i);
    assert.throws(() => prepareKitDraft({config: configured(), issue: i, locale: 'en'}));
  }
});

test('HTML and Liquid injections are neutralized; only trusted footer tokens remain', () => {
  const i = structuredClone(issue);
  i.items[0].en.title = '<script>bad()</script> {{ subscriber.email_address }}';
  i.items[0].en.summary = '{% include "malicious" %} &#123;{private}}';
  const p = prepareKitDraft({config: configured(), issue: i, locale: 'en'});
  assert.ok(p.payload.content.includes('&lt;script&gt;'));
  assert.ok(!p.payload.content.includes('<script>'));
  assert.ok(!p.payload.content.includes('{%'));
  assert.deepEqual(p.payload.content.match(/{{[^}]+}}/g), ['{{ address }}', '{{ unsubscribe_url }}']);
  assert.ok(!p.payload.content.includes('<!--PROVIDER_FOOTER-->'));
  for (const field of ['title', 'coverage']) {
    const altered = structuredClone(issue); altered[field].en = '{{ private }}';
    assert.throws(() => prepareKitDraft({config: configured(), issue: altered, locale: 'en'}));
  }
});

test('enabled without exact approval remains a local preview', async () => {
  const {args} = setup(); delete args.approval; args.fetcher = () => assert.fail();
  args.ledger.claim = () => assert.fail();
  assert.equal((await createKitDraft(args)).status, 'local_preview');
});

test('approval rejects changed content, locale, sender, template or audience with no side effect', async () => {
  for (const change of [a => a.approval.action = 'send', a => a.approval.extra = true, a => a.locale = 'zh-TW',
    a => a.issue.items[0].en.title += ' update', a => a.approval.date = '2000-01-01',
    a => {a.config.sender_email = 'new@example.com'; a.config.sender_verification.email_address = a.config.sender_email;},
    a => {a.config.locales.en.segment_id = 99; a.config.locales.en.audience_verification.segment_id = 99;},
    a => {a.config.locales.en.email_template_id = 99; a.config.locales.en.template_verification.email_template_id = 99;},
    a => a.config.site_url += '/other']) {
    const {args} = setup(); change(args); args.fetcher = () => assert.fail(); args.ledger.claim = () => assert.fail();
    await assert.rejects(() => createKitDraft(args));
  }
});

test('explicit fake transport creates only one confirmed draft per edition-language', async () => {
  const {args, states} = setup(); let calls = 0;
  args.fetcher = async (url, options) => {
    calls++; assert.equal(url, 'https://api.kit.com/v4/broadcasts'); assert.equal(options.method, 'POST');
    assert.equal(options.redirect, 'error'); assert.ok(options.signal instanceof AbortSignal);
    assert.equal(options.headers['X-Kit-Api-Key'], 'fake-unit-key');
    const p = JSON.parse(options.body); assert.equal(p.public, false); assert.equal(p.send_at, null);
    return reply(p, b => {b.subscriber_filter[0].any = null; b.subscriber_filter[0].none = null;
      b.published_at = p.published_at.replace('Z', '+00:00');});
  };
  assert.equal((await createKitDraft(args)).status, 'draft_created');
  assert.equal((await createKitDraft(args)).status, 'already_reserved'); assert.equal(calls, 1);
  assert.deepEqual(states.map(s => s.state), ['reserved', 'draft_created']);
  args.issue.items[0].en.title += ' revised';
  args.approval.digest = prepareKitDraft(args).digest;
  assert.equal((await createKitDraft(args)).status, 'already_reserved'); assert.equal(calls, 1);
});

test('snapshot survives caller mutation while the durable claim is pending', async () => {
  const {args} = setup();
  args.ledger.claim = async () => {args.config.sender_email = 'bad@example.com'; args.issue.title.en = 'changed'; return true;};
  args.fetcher = async (_, options) => {
    const p = JSON.parse(options.body); assert.equal(p.email_address, 'newsletter@example.com');
    assert.ok(!p.subject.includes('changed')); return reply(p);
  };
  assert.equal((await createKitDraft(args)).status, 'draft_created');
});

test('missing transport, secret, ledger or malformed approval fails before reservation', async () => {
  for (const change of [a => a.apiKey = '', a => a.apiKey = 'key\nsecret', a => a.fetcher = undefined,
    a => a.ledger.update = null, a => a.approval = {}, a => a.approval.digest = 'invalid']) {
    const {args} = setup(); args.fetcher = () => assert.fail(); args.ledger.claim = () => assert.fail();
    change(args); await assert.rejects(() => createKitDraft(args), /Exact draft approval/);
  }
});

test('unconfirmed provider state, broadened audience and bad responses remain reserved', async () => {
  const changes = [b => b.status = 'scheduled', b => b.public = true, b => b.send_at = '2999-01-01T00:00:00Z',
    b => b.public_url = 'https://example.kit.com/post', b => delete b.public_url,
    b => b.subscriber_filter = [], b => b.subscriber_filter[0].all[0].ids.push(99),
    b => b.subscriber_filter[0].any = [{type: 'tag', ids: [99]}], b => b.email_address = 'bad@example.com',
    b => b.email_template.id = 99, b => b.subject = 'changed', b => b.preview_text = 'changed',
    b => b.description = 'changed', b => b.published_at = '2000-01-01T00:00:00Z',
    b => b.published_at = '2026-10-03T24:00:00Z', b => b.content = 'changed', b => b.id = null];
  for (const change of changes) {
    const {args, states} = setup(); let calls = 0;
    args.fetcher = async (_, options) => {calls++; return reply(JSON.parse(options.body), change);};
    await assert.rejects(() => createKitDraft(args), /uncertain/);
    assert.equal(states.at(-1).state, 'uncertain');
    assert.equal((await createKitDraft(args)).status, 'already_reserved'); assert.equal(calls, 1);
  }
});

test('network, response limit and parser errors are sanitized and never retried', async () => {
  for (const fetcher of [async () => {throw new Error('private@example.com fake-unit-key');},
    async () => new Response('private@example.com', {status: 429}),
    async () => new Response('{}', {status: 200, headers: {'Content-Type': 'application/json'}}),
    async () => new Response('private', {status: 201, headers: {'Content-Type': 'application/json'}}),
    async () => new Response('x'.repeat(1024 * 1024 + 1), {status: 201, headers: {'Content-Type': 'application/json'}})]) {
    const {args, states} = setup(); args.fetcher = fetcher;
    await assert.rejects(() => createKitDraft(args), e => /uncertain/.test(e.message) && !/private|fake-unit-key/.test(e.message));
    assert.equal(states.at(-1).state, 'uncertain'); assert.equal((await createKitDraft(args)).status, 'already_reserved');
  }
});

test('ledger failures do not leak private details or trigger an unreserved request', async () => {
  const {args} = setup(); args.ledger.claim = async () => {throw Error('private@example.com');}; args.fetcher = () => assert.fail();
  await assert.rejects(() => createKitDraft(args), /reservation failed; no provider request/);
  const second = setup(); second.args.ledger.update = async () => {throw Error('private@example.com');};
  second.args.fetcher = async (_, options) => reply(JSON.parse(options.body));
  await assert.rejects(() => createKitDraft(second.args), /outcome uncertain/);
  assert.equal((await createKitDraft(second.args)).status, 'already_reserved');
});

test('offline CLI reports disabled configuration and sanitizes invalid-file errors', async () => {
  const script = new URL('../../scripts/newsletter/kit-readiness.mjs', import.meta.url).pathname;
  const configPath = new URL('../../newsletter/examples/kit-config.example.json', import.meta.url).pathname;
  const result = spawnSync(process.execPath, [script, configPath], {encoding: 'utf8'});
  assert.equal(result.status, 0, result.stderr); assert.equal(JSON.parse(result.stdout).remote_verified, false);
  const dir = await mkdtemp(join(tmpdir(), 'kit-readiness-'));
  try {
    const path = join(dir, 'config.json'); await writeFile(path, '{"private@example.com":');
    const bad = spawnSync(process.execPath, [script, path], {encoding: 'utf8'});
    assert.equal(bad.status, 2); assert.ok(!bad.stderr.includes('private@example.com')); assert.ok(!bad.stderr.includes(dir));
    const c = configured(); c.locales.en.audience_verification = null; await writeFile(path, JSON.stringify(c));
    assert.equal(spawnSync(process.execPath, [script, path]).status, 1);
    await writeFile(path, 'x'.repeat(65537)); assert.equal(spawnSync(process.execPath, [script, path]).status, 2);
  } finally { await rm(dir, {recursive: true, force: true}); }
});
