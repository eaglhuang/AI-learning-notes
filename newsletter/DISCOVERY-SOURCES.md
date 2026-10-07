# Newsletter discovery sources

This document describes the October 7, 2026 source-readiness increment. It does not activate a service, account, feed subscription or daily scheduler. The runtime source list is `daily/data/sources.json`; `daily/data/source-catalog.json` is a separately labeled editorial discovery catalog.

## Actual collection state

OpenAI, Hugging Face, arXiv AI and Simon Willison remain the four enabled feeds. The configured daily window is two days, measured as exactly 48 hours backward from the timezone-aware collection instant, with both endpoints inclusive. An article one second outside the window is excluded. An update timestamp or a provider's first-seen timestamp can supply a candidate lead, but cannot prove publication time. Reviewed pipeline previews require a verified `published_at` with a timezone and its matching `published_date`.

The edition date is the Asia/Taipei calendar date of collection. An offline saved report must match that date, and its collection timestamp cannot be later than the trusted run clock. This rejects coherent-looking future reports even on the same calendar day. The static publication validator, offline writer and optional email renderer use the same Taipei calendar for edition/review dates, including before UTC midnight; this does not activate a writer or email service. Research users may explicitly choose another supported 1–30-day window; those reports are not the approved daily 48-hour profile. A quiet day or failed source does not widen the daily window automatically.

Four additions have documented endpoints but remain disabled and live-fetch untested in this change:

| Source | Documented endpoint | Evidence and limits |
| --- | --- | --- |
| arXiv machine learning | https://rss.arxiv.org/rss/cs.LG | [Official RSS guide](https://info.arxiv.org/help/rss.html) documents subject-class RSS/Atom paths. Check the individual paper version and license. |
| arXiv computation and language | https://rss.arxiv.org/rss/cs.CL | Same official guide; cross-listed papers must collapse to one event. RSS availability is not an article translation license. |
| CNA technology | https://feeds.feedburner.com/rsscna/technology | [CNA RSS page](https://www.cna.com.tw/about/rss.aspx) links this endpoint and states reuse conditions. Its feed is a lead with headline/introduction/link, not blanket permission to republish or translate a full article. |
| Martin Fowler | https://martinfowler.com/feed.atom | [Author FAQ](https://martinfowler.com/faq.html) identifies the feed and discusses syndication and translation. Verify actual authorship and per-article exceptions, including guest authors. |

`enabled` must be a JSON boolean. A disabled source is not fetched, receives no successful fetch receipt and is listed in `disabled_sources`. For active sources, `feed_hosts` and `article_hosts` are separate exact-host allowlists. Redirects remain refused. No credentials, dynamic host expansion or third-party link decoding is introduced.

## Google News headline discovery

Use the public [Taiwan / Traditional Chinese headlines](https://news.google.com/home?ceid=TW:zh-Hant&gl=TW&hl=zh-TW) and [English / United States headlines](https://news.google.com/home?ceid=US:en&gl=US&hl=en-US) as editorial discovery routes. [Google's explanation of story selection](https://support.google.com/googlenews/answer/9005749?hl=en) distinguishes regional/language headlines and personalized sections. These pages are not an official programmable feed or API contract. This increment implements neither a Google News scraper nor undocumented RSS endpoints; it does not claim current headline fetch verification.

For each lead, record the discovery URL, observed time, region/language, section, observed position if visible, displayed publisher, and original article URL. A displayed position is an observation at that time, not a universal popularity score. Do not count Google News as an additional independent news outlet. If the original source or its publication instant cannot be verified, keep the lead pending rather than publishing the aggregator snippet as a verified story.

Prefer significant AI-relevant stories for the two featured positions when the underlying evidence supports them. Relevance, concrete effects, primary-source support and genuinely independent coverage matter more than vendor prominence. Multiple syndicated copies, mirrors, quote posts or pages repeating one press release do not establish independent corroboration. Do not fabricate a numerical importance score or force two 'major breaking news' claims when the day lacks such evidence.

## Engineering authors and diverse channels

The catalog includes practitioner writing, research, open-source releases, independent technology reporting and Taiwan/Asia channels. Representative primary author routes include Simon Willison, Martin Fowler, Kent Beck, Charity Majors, Andrej Karpathy and Paul Graham. This is a starting inventory, not an exclusive celebrity list. A substantive software-engineering article can be more relevant than a launch announcement.

Confirm author identity from the author's own site, biography or linked official account. Read the actual byline: a site owner is not necessarily the author of a guest article or embedded quotation. Simon's [about page](https://simonwillison.net/about/) describes a combined feed containing several kinds of posts. The collector therefore preserves bylines with `byline_verification_required: true` and initially labels their type `unclassified_feed_entry`.

Separate reported events, the author's experience, hypotheses and opinions. Attribute an author's conclusions instead of presenting them as an independent measured result. An older essay discovered or linked today retains its original date; it is background, not fresh daily news. Titles, summaries, highlights and caveats must follow the existing source-only bilingual policy without adding this newsletter's opinions or advice.

## Evidence, rights and cross-edition deduplication

Source-family, region and rights metadata are contextual leads, not certificates. `full_translation_eligibility` remains unknown, permission-required, or explicitly conditional. Public access, RSS syndication, an open-source repository license or a site's general statement does not automatically authorize translating every linked article or reusing every image. Preserve applicable source/author/license links and review the particular material. Full translation remains disabled.

The CLI and isolated pipeline read all validated published issues. Normalized URL identity removes fragments and recognized tracking parameters but keeps meaningful query values. Exact explicit `event_id` matches also exclude prior events even when their URLs differ. The same event covered by several sources still requires editorial event comparison: no automatic semantic clustering or factuality classification is claimed. A stable changelog URL is conservatively excluded if published before; a distinct new dated event needs a separately reviewed selection rather than an automatic exception.

Candidate reports retain source context, byline, fetch receipts, failure diagnostics and an exact window envelope. Imported reports must match the selected source configuration. Altering rights metadata, concealing a failed feed, using a disabled source or rounding away an expired timestamp blocks preparation. Original evidence stays immutable through selection and preview. A report can be partial with zero candidate results; an outage must not become a successful empty result.

## Verification and safe activation

1. Run `python -B scripts/newsletter/source_config.py --check` and the existing Python/Node/build checks. Offline fixtures cover RSS, Atom and RDF, disabled sources, distinct feed/article hosts, failure receipts, precise boundaries, bylines, configuration binding and historical exclusion.
2. Before activating any additional feed, verify its documented endpoint, response format, redirects, bounded response size, article hosts, timestamps, bylines and current reuse conditions with a separately permitted bounded fetch. A timeout, rate limit or access denial is recorded; do not loop or change routes to bypass it.
3. Review an actual sample against original pages and prior editions. Resolve missing publication times and mixed-author feeds before a publication decision. Then submit the narrow `enabled` configuration change for normal review. This document does not itself enable it.
4. Check Google News/expert leads manually against the criteria above. The original planning inventory contained 37 proposed checks; 20 are editorial review rules about identity, attribution, importance, dates and rights. The executable fixtures do not claim to prove those judgments.

This increment uses no network in its tests, no paid API, no account signup, no secret configuration, no email and no new scheduler. It does not create another October 7 edition. Live service availability and new-feed coverage remain unverified until the activation checks are actually performed.
