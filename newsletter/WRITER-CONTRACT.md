# Offline bilingual writer contract

This is a local request/response boundary, not a connected LLM or automatic news
writer. It prepares a private request from a blank pipeline selection and source
text, then validates a separately supplied response. It never calls a provider,
loads credentials, spends money, verifies facts automatically, publishes, sends
email, or marks an edition reviewed. `invoke_live_writer` always refuses.

## Prepare a private request

Start a fresh pipeline run using the current source version. Keep the original
`selection.json`; do not overwrite an editor's work in `draft.json`.

```sh
python -B scripts/newsletter/writer.py prepare \
  --draft /tmp/newsletter-run/selection.json \
  --sources /tmp/newsletter-source-bodies.json \
  --config newsletter/examples/writer-config.example.json \
  --output /tmp/newsletter-writer-request.json
```

The source bundle must contain `schema_version: 1` and a `documents` array in the
same order as the selected items. Each document has exactly these fields:

```json
{
  "item_id": "copy the exact selected ID",
  "source_url": "copy the exact selected HTTPS URL",
  "source_title": "copy the original evidence source_title",
  "content_kind": "article_body",
  "content_text": "The substantive text copied from the authorized original source, not a headline or search snippet.",
  "retrieved_at": "2026-10-06T04:00:00Z",
  "acquisition": "operator_supplied"
}
```

This example explains the shape and is intentionally not a valid story. Supply
one actual source document for every selected story. Supported content kinds are
`article_body`, `official_announcement`, and `paper_abstract`. The operator must
verify that the content belongs to the original URL and accurately identify its
scope. The code does not fetch or authenticate that content. A full primary
abstract is allowed even if the same text appeared in an arXiv feed; do not claim
it is the full paper. Respect source rights and access restrictions.

Content must contain 240–100,000 characters, with enough variation to reject
simple repeated filler. These checks are a coarse floor, not proof of substance,
authenticity or sufficient evidence. Title-only content, explicitly labeled
search snippets, mismatched source identities, future/invalid timestamps, missing
documents and extra document fields are rejected. Do not pad or rewrite source
text merely to pass a length check.

The request binds the exact draft, source content hashes, topic and coverage
diagnostics. Trusted instructions and the output contract are separate from
source-data strings. Instruction-like text inside a source remains data, with no
tool execution or instruction-role promotion. This separation reduces accidental
instruction mixing; it does not claim to make a future model immune to prompt
injection. No source URL is automatically visited.

## Validate a saved response

The request includes `output_contract` and `request_digest`. An imported response
must follow the exact contract, retain every selected ID/URL/order, and provide:

- All issue fields and every item title, summary, takeaway and caveat in both
  `zh-TW` and `en`, within the existing editorial text limits
- One exact 12–240 character quote from the corresponding supplied source for
  each item field in each language; references to selected IDs for issue fields
- A statement that limitations were included in both languages, plus positive
  reported input/output token counts within the configured ceilings

```sh
python -B scripts/newsletter/writer.py apply \
  --draft /tmp/newsletter-run/selection.json \
  --request /tmp/newsletter-writer-request.json \
  --response /tmp/newsletter-writer-response.json \
  --output-dir /tmp/newsletter-written
```

This command does not generate the response. In this delivery, all exercised
responses are synthetic offline test fixtures, not model output or news content.
No externally obtained response is uploaded or inferred to have permission for
provider use merely because it can be parsed.

The output directory must be new and outside the repository. It contains:

- `draft.json`: editorial text filled in, still `reviewed: false`, with an empty
  `reviewed_on`. Original source evidence, topic, dates, date-verification flags
  and discovery limitations are unchanged
- `WRITER-REVIEW.json`: private support quotes, source hashes, reported usage and
  explicit unverified fact/language/date/billing status

The request and output files are owner-only from creation (0600, subject to any
more restrictive umask), and the result directory is 0700. Writes publish via an
atomic no-clobber operation. Existing files and editorial text are never silently
replaced. An interrupted multi-file result may leave a partial new directory;
inspect it and choose a new output directory rather than retrying over it.
Inputs with duplicate JSON keys, oversized files, symlink paths, or public-repo
output destinations are rejected. Contract errors are actionable without quoting
source text; filesystem/parse errors do not echo file content or private paths.

Keep the request, source bundle and review packet private. They may contain
copyrighted source text or private notes. Do not publish the entire working
folder or copy the review packet into the public issue JSON. Only the editorial
draft should enter the existing human review flow.

## What the checks cannot establish

An exact quote can be irrelevant to a claim. A valid JSON object can contain a
false summary. A Han character in the Chinese summary and a Latin word in the
English summary are only basic script checks, not proof of Traditional Chinese,
fluency, faithful translation, equal meaning or factual entailment. The review
packet explicitly sets these verification claims to false. Partial-source
acknowledgement stays false even if the model claims it included the limitations.

A human must read the originals, confirm supporting claims and dates, distinguish
inference from facts, compare both languages, remove unsupported text, verify
originality, and review known search failures. The writer does not repair missing
publication dates or change date verification flags. Complete that work before
setting the normal editorial review fields and using the existing preview:

```sh
python -B scripts/newsletter/pipeline.py preview \
  --run-dir /tmp/newsletter-run \
  --reviewed-issue /tmp/newsletter-written/draft.json
```

The pipeline rejects the generated draft until a human completes review. Its
original immutable selection/source gates continue to apply. A preview still
does not publish or send anything.

## Token and cost boundaries

The example is deliberately unconnected: provider/model/pricing are null,
`max_cost_usd` is `"0.00"`, and `live_enabled` must be false. There is no invented
provider rate or account entitlement. Input and response byte ceilings are
measured locally; oversized input is refused rather than silently truncated.

Token ceilings check only the imported response's reported counts. No provider
tokenizer has been selected, so the request reports `tokenizer_verified: false`.
This is not a guarantee of actual prompt tokens, billed tokens or spend. If an
operator supplies declared pricing, the configuration must bind it to an explicit
provider/model and verification date. Decimal arithmetic checks the configured
maximum input/output token counts against `max_cost_usd`, and separately computes
declared usage cost. The report still says `billing_verified: false`.

The optional pricing object has fields `provider`, `model`,
`input_usd_per_million`, `output_usd_per_million`, and `verified_on`. Rates and
budget are nonnegative decimal strings, not floating point. Test prices are
fictional. Never infer actual service prices from fixtures. The timeout is bounded
and maximum attempts is one, but neither performs or governs a live call here.

Before a future live adapter can be implemented and used, the owner must select
and approve the provider/model, exact source-data transmission scope, and spending
ceiling. That adapter must verify the applicable tokenizer, current complete
billing rules including reasoning/tool charges, service limits, actual usage,
timeouts and durable retry/reservation behavior, and use the supported credential
handoff. Unknown pricing or count semantics must block calls. Flipping the current
flag or supplying a callback cannot enable live generation.
