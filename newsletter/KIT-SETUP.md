# Kit readiness: disabled until separately approved

This increment provides a server-only interface and offline configuration checks.
It does not connect an account, read credentials, create a subscriber or broadcast,
send email, enable a schedule, or alter the public website's subscription control.
The existing optional generic/Brevo adapter is preserved. Do not pass the Kit
draft function into `deliverEdition`: that older operation includes sending.

## Check the included configuration

```sh
node scripts/newsletter/kit-readiness.mjs newsletter/examples/kit-config.example.json
node --test tests/newsletter/kit.test.mjs
```

Both feature flags default to false. The example contains no IDs or credentials.
The checker prints missing requirements without printing sender addresses, form
URLs, file paths, credentials, or provider response bodies. Exit 0 means a valid
configuration, possibly disabled and incomplete. Exit 1 means invalid settings or
an enabled feature missing requirements; exit 2 means a file/CLI error.
`remote_verified: false` always means **no Kit account state was checked**.
Never put keys in this JSON, the site config, source control, or browser code.

## Subscription handoff and double opt-in

The supported interface is `kitSubscriptionHandoff(config, locale)`. Disabled
configuration returns no URL. Enabled and locally verified configuration returns
the selected language's copied first-party hosted-form URL. This helper collects
no address and returns `subscription_confirmed: false`. The website is not wired
to it in this increment.

After separate setup/activation approval, an operator must verify in Kit:

1. Two distinct hosted forms and URLs, one for `zh-TW`, one for `en`. Copy actual
   form IDs and hosted URLs; do not infer IDs from URLs. Only a single creator
   subdomain under `kit.com` or `ck.page` is accepted here. Custom domains are a
   separate reviewed integration.
2. Incentive/confirmation email is enabled and auto-confirm is off. Check the
   correct-language confirmation message and post-confirmation destination.
3. The form clearly identifies the newsletter, selected language, data recipient
   and purpose. Preserve explicit, unchecked consent; verify its privacy notice
   and unsubscribe path. Do not silently switch a reader to another language.
4. Test pending → confirmed and unsubscribe behavior with an approved test
   address before enabling a live handoff. Never treat a form visit or API
   acceptance as a confirmed subscription.

Record an operator attestation under each locale, bound to exactly that form:

```json
{
  "locale": "en",
  "form_id": 2,
  "hosted_url": "https://example.kit.com/en",
  "confirmation_email_enabled": true,
  "auto_confirm": false,
  "consent_notice_verified": true,
  "checked_on": "2026-10-06"
}
```

These are illustrative values, not a real form or proof. Do not copy attestations
without performing the checks. Changing the ID, locale or URL invalidates the
attestation. Configuration assertions cannot prove future service settings or
enforce remote consent; recheck them before activation and after changes.

Kit's create-subscriber API defaults to an active subscriber. This module does
not use it or infer DOI from a generic subscriber upsert. Hosted form behavior
depends on the actual account settings. See the official
[subscriber API](https://developers.kit.com/api-reference/subscribers/create-a-subscriber)
and [form confirmation guidance](https://help.kit.com/en/articles/2502655-the-confirmation-email).

## Draft broadcasts: one explicit language audience

`prepareKitDraft({config, issue, locale})` is a pure local preview. It reuses the
existing validated email renderer, requiring a real, reviewed, complete bilingual
edition. Editorial approval is not approval to upload content to Kit.

Before later account use, verify API eligibility on the actual Kit plan, the
sender identity/address, and an explicit Classic email template per language.
There is no account-default sender or template fallback. Verify the template
renders the supplied HTML, postal address and unsubscribe footer correctly;
Starting Point templates are outside this contract. Do not assume mock tests
prove service entitlement or actual email rendering.

Local configuration requires:

- `sender_verification`: `{ "email_address": "newsletter@example.com", "checked_on": "2026-10-06" }`
- Per-language `audience_verification`: `{ "locale": "en", "segment_id": 12, "confirmed_only": true, "exclusive_language": true, "checked_on": "2026-10-06" }`
- Per-language `template_verification`: `{ "locale": "en", "email_template_id": 22, "template_type": "classic", "footer_verified": true, "checked_on": "2026-10-06" }`

Use real verified values only after authorization. Distinct segment IDs alone do
not prove disjoint audiences. Inspect the filters and membership: only confirmed
consenting readers of that language, excluding unsubscribed/suppressed readers.
The operator must recheck dynamic membership before any later send. This module
has no send function and performs no recipient-count or final-send approval.

Every generated request has `public: false`, `send_at: null`, an explicit sender,
explicit template ID, and exactly one `all` filter containing one language
segment. It never omits the filter or targets all subscribers. `published_at`
holds the edition date because Kit documents this body field; the request remains
private and unscheduled. See the official
[create-broadcast contract](https://developers.kit.com/api-reference/broadcasts/create-a-broadcast)
and [segment guidance](https://help.kit.com/en/articles/2577659-how-to-create-a-segment).

Classic receives a body fragment with inline styling, not a nested HTML document.
Untrusted HTML is escaped by the renderer. All untrusted curly braces are then
neutralized before adding only the documented trusted `address` and
`unsubscribe_url` Liquid variables. Plain subject/preview text rejects Liquid
syntax and control characters. No remote images, scripts, or template code are
added from source feeds.

## Future server orchestration contract

`createKitDraft` receives the config, issue, locale, exact approval, an injected
durable ledger, a server-held API key and an explicitly injected transport. It
does not load secrets, select global `fetch`, retry, or configure persistent
access. Tests supply a fake key and mocked transport only.

- With `drafts_enabled: false`, it returns `disabled`
- Enabled without approval returns only the local preview
- Approval must contain exactly `action: "create_kit_draft"`, date, locale and the
  preview digest. The digest binds the complete HTML and request target settings
- `ledger.claim(key, value)` must atomically persist a create-if-absent reservation
  and return a boolean. `ledger.update` must persist updates. An in-memory set is
  suitable only for tests, never production
- The key is edition date + language, not content digest. Editing a draft cannot
  silently create another broadcast for the same issue-language
- Only the fixed HTTPS V4 broadcast endpoint is used, with redirects refused and
  a 15-second timeout signal. The injected production transport must honor that
  signal. Response parsing is bounded to 1 MiB
- A confirmed success must be a matching draft, private and unscheduled, with the
  approved audience, sender, template and content. It means `draft_created`, never
  sent, scheduled, published or subscribed
- An HTTP error, timeout, mismatched response or ledger failure leaves a durable
  reservation and reports `uncertain`. Inspect Kit and the ledger manually before
  any separately approved retry. Do not delete a reservation to force success

Creation would upload edition content and sender/target IDs to Kit. Local code
approval does not authorize that operation. Account creation, API access/keys,
sender/domain changes, real draft creation, live subscriptions, and sending each
remain outside this delivery's activation authority. Credentials require the
supported secure handoff, not chat or committed configuration. Kit API eligibility
must be checked against its [current overview](https://developers.kit.com/api-reference/overview).

## Autonomous bilingual writer: still a separate missing stage

The pipeline currently produces source-bound, unreviewed drafts with blank
bilingual editorial fields. No model, paid service or autonomous writer is
configured. Before implementing that stage, select an approved provider/model,
credential route, source-data transmission scope, per-run spending/token budget,
timeout/retry policy and structured-output contract. Keep `reviewed: false` even
when generation succeeds; a model cannot authorize its own publication.

A writer must preserve selected IDs, canonical URLs, original evidence and topic
matches; distinguish publication dates from observed/updated dates; generate both
languages from the same verified source facts; retain search-coverage limitations;
and refuse missing/unverifiable facts rather than inventing summaries. A GDELT
title or snippet alone is not full-article verification. Source retrieval should
remain bounded, HTTPS-allowlisted, copyright-aware, and treat page text as data,
never instructions. Partial results and provider failures must remain visible.
The existing editorial gate and immutable run snapshots remain authoritative.
