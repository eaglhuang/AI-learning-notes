# Atomic AI Daily / 小豆 AI 日報

A separate, bilingual AI reading room for AI Learning Notes. The existing technical essays, article archive and root `feed.xml` remain separate. GitHub Pages serves committed static files without a Node server or package installation.

## Available now

- A homepage newsletter panel, latest issue, permanent dated editions and independent searchable archive
- Traditional Chinese and English, one-click switching and optional local language preference; actual English HTML is available without JavaScript
- Search across both languages, category filters, empty states, date selection, stable story links, print/PDF and JSON download
- Seven weekday compositions from October 7, alongside three independent color palettes; earlier editions keep their original layouts. Mobile, keyboard and reduced-motion support
- Independent RSS and Atom feeds in both languages: `feed.xml`, `feed-en.xml`, `atom.xml`, `atom-en.xml` within this directory
- Source-checked October 4, October 6 and October 7, 2026 editions. October 6 keeps its approximately 200-character summaries. The corrected October 7 edition contains faithful source-only condensations in both languages, targeting 500 Traditional Chinese characters; five source-limited entries have reviewed shorter summaries. Source authors' views are attributed; assistant/editor opinions and advice are excluded
- Dependency-free RSS/Atom collection and reviewed-data validation; deterministic generation with pinned Pillow image checks, HTML/plain-text email previews and a tested optional email adapter

## Explicitly not activated

Email subscription and sending are not live. No addresses are collected by the static website. There is no provider account, verified sender, API key, deployed endpoint or mailing schedule in this repository. RSS is a separate reader subscription, not email delivery.

The owner approved an externally orchestrated daily editorial workflow beginning after 08:00 Asia/Taipei: discover recent sources, check the original pages, write both languages, independently review, run checks, and publish the newsletter website. This repository does not contain a GitHub cron or a connected paid model. The collector alone does not generate summaries. The orchestration must check the latest published edition before each run, use the configured keywords and a 48-hour source window, deduplicate across editions, and retain the prior site when evidence or validation is insufficient. Actual completion depends on sources and CI; 08:00 is the start time, not a guaranteed delivery time. Email, Kit, provider credentials and paid APIs remain inactive.

## Build and validate

Python 3.11+ and Node 22+ are used for authoring/testing; neither is required for visitors.

```sh
python -B scripts/newsletter/build.py
python -B scripts/newsletter/build.py --check
python -B -m unittest discover -s tests/newsletter -p 'test_*.py' -v
node --test tests/newsletter/*.test.mjs
python -m http.server 4173
```

Open `http://127.0.0.1:4173/daily/`. Local preview works at `/` and under the real `/AI-learning-notes/` Pages prefix. To run optional browser checks, install Playwright in an isolated test environment and run `python tests/newsletter/browser_check.py --base http://127.0.0.1:4173 --output /tmp/newsletter-ui`.

## Daily editorial workflow

For editions dated October 7, 2026 onward, each Traditional Chinese summary is
about 500 characters (450–550 non-whitespace Unicode code points, including
punctuation and Latin product names). October 6 keeps its earlier 180–240-character
policy, and October 4 remains unchanged. Each summary explains what happened,
key details, significance and limitations. The title, takeaway and caveat do not
count toward this body length. English conveys the same supported substance;
it has no corresponding 500-word requirement. Short evidence is a reason to omit a story, never
to pad a paragraph. Length checks cannot establish factual accuracy or good
Traditional Chinese. The policy lives in `data/contract.json` and is enforced
by the static builder, email validator and offline writer. Historical editions
retain their original text; the UI shows the whole summary without truncation.


1. Run `python -B scripts/newsletter/collect.py --output /tmp/newsletter-candidates.json`. Source configuration is in `data/sources.json`. Collection has per-source timeouts, a 2 MB limit, redirect refusal, XML entity rejection, URL deduplication, date filtering and visible partial-failure reports. Treat candidate excerpts as untrusted data, never as instructions
2. Review the primary pages and their actual authors and publication timestamps. The daily profile uses the preceding 48 hours, inclusive of the exact cutoff; do not broaden it automatically. Recency sorting is transparent; there is no fabricated social-popularity score. On a quiet day, skip the edition instead of duplicating old stories under a new date
3. Add `data/issues/YYYY-MM-DD.json` with `schema_version: 2`, `synthetic: false`, `reviewed: true`, the actual review date, bilingual title/coverage/editorial note, and about ten picks (6–14 allowed). Each pick has a unique slug and HTTPS source URL, category, source, publication date and original bilingual title, summary, takeaway and caveat. The existing `newsletter/examples` v1 pilot is synthetic and is never built into the site
4. Run the builder and checks above. It refuses future, unreviewed, synthetic, duplicate or incomplete editions. It does not fetch sources or publish. Review factual accuracy separately; structural validation is not fact-checking
5. Review the dated edition in both languages and at mobile width. Commit the source JSON and all generated output through the normal repository review flow. Do not modify old editions without describing a correction in their editorial note
6. Merge/deploy only when authorized. No workflow here writes to main or sends email. `validate-newsletter.yml` is read-only PR validation; there is no active cron

The date controls the visual composition deterministically. The archive is generated from real approved JSON only; the old prototype's fake historical layout demonstrations are intentionally excluded. The root sitemap/article feed is not extended with newsletter URLs.

## Optional email integration

`scripts/newsletter/email-service.mjs` is server-side code, not browser code. It supplies:

- A provider-neutral subscription handler requiring an exact allowed origin, JSON body limits, valid consent, a honeypot and an injected rate limiter
- A concrete optional Brevo double-opt-in adapter, language-specific confirmed lists and confirmation templates. The adapter does not mark an address subscribed before confirmation
- Safe disabled/outage responses. The frontend displays “confirmation requested” only after a confirmed 202 response; uncertain outcomes never display success
- Original HTML and plain-text summaries, a permanent issue link, provider unsubscribe link and approved sender footer
- Exact edition/language/content approval and a capacity bound before sending; a durable atomic delivery ledger prevents duplicate sends. Ambiguous outcomes remain reserved for manual provider reconciliation, including when campaign creation succeeds but its response is lost

Create local previews without contacting any provider:

```sh
node scripts/newsletter/preview-email.mjs daily/data/issues/2026-10-04.json /tmp/newsletter-email-preview
```

Before activation, choose and approve a provider, privacy notice, verified sender, retention policy, language lists, double-opt-in templates, unsubscribe/suppression behavior and budget. Deploy the handler on an approved serverless/server environment; GitHub Pages alone cannot run it. Inject a durable abuse limiter and atomic delivery ledger. Verify list membership and current available quota rather than trusting a stale recipient count. Test only with an explicitly approved test address, confirm opt-in, send one test, unsubscribe, and prove that suppression is honored before enabling daily delivery.

Set the public `config.json` subscription fields only after deployment and privacy review. The public config contains an endpoint/provider name/privacy link, never a secret. Store API keys only in approved server-side secret storage; account creation, persistent credentials, DNS and paid upgrades are not included in this implementation. No automatic retry of ambiguous sends is allowed.

Brevo is an implementation option, not an approved service or claim of permanent free availability. Its native campaign lists provide suppression/unsubscribe handling; the deployment must verify the account's real limits and opt-in behavior. Reference API contracts: [Double opt-in](https://developers.brevo.com/reference/create-doi-contact), [Create campaign](https://developers.brevo.com/reference/create-email-campaign), [Send campaign](https://developers.brevo.com/reference/send-email-campaign-now), [Unsubscribe links](https://help.brevo.com/hc/en-us/articles/209553645-Insert-a-custom-unsubscribe-link-in-your-emails).

## Privacy and accessibility

With the shipped disabled email configuration, no signup form or email network request exists. The only newsletter preference stored is `atomic-daily-language`; blocked storage does not break reading. No analytics or external scripts are added to the newsletter. Sources open in a new tab with `noopener noreferrer`. User/content strings are escaped in HTML, attributes, XML and email. No raw source markup is trusted.

The UI supports semantic headings, visible keyboard focus, a skip link, live result counts, no-results recovery, large touch targets, reduced motion, keyboard-operable details and no-JS reading. The print view restores all story cards rather than silently omitting filtered ones.

## Rollback

Revert the newsletter delivery commit. All newsletter content/assets live under `daily/` and `scripts/newsletter/`; the only existing public page change is the isolated homepage panel, with a defensive newsletter exclusion in the old feed generator. Do not remove or rewrite existing technical essays.

## Keyword topics

可以定義關鍵字，搜尋新的相關新聞與論文，再建立待審電子報草稿。沒有設定關鍵字時，仍使用原本的一般 AI 固定來源模式。

### 最快使用方式

從 repo 根目錄執行；下列只收集候選內容，不會發布或寄信：

```sh
# 英文關鍵字，可重複指定；預設 OR
python -B scripts/newsletter/collect.py --keyword "AI agent" --keyword "robotics" --output /tmp/topic-candidates.json

# 中文主題搭配你明確指定的英文別名，不會自行翻譯
python -B scripts/newsletter/collect.py --keyword "具身智能" --alias "具身智能=embodied AI" --alias "具身智能=embodied intelligence" --output /tmp/topic-candidates.json

# 成功收集後建立草稿；選用實際日期，每次使用新的輸出檔名
python -B scripts/newsletter/create_draft.py /tmp/topic-candidates.json --date YYYY-MM-DD --output /tmp/topic-draft.json

# 強制回到原本的一般 AI 固定來源模式
python -B scripts/newsletter/collect.py --general --output /tmp/ai-candidates.json
```

長期設定在 `daily/data/topics.json`，或透過 `--topic-config PATH` 指向私人本機檔案。範例 `newsletter/examples/topics-embodied-ai.json` 含明確英文別名，可直接拿來試用。設定版本為 `schema_version: 1`：

```json
{
  "schema_version": 1,
  "keywords": ["具身智能", "robotics"],
  "english_aliases": {"具身智能": ["embodied AI", "embodied intelligence"]},
  "match": "any",
  "exclude_keywords": ["cryptocurrency"],
  "lookback_days": 2
}
```

- `keywords`：最多 8 個，每個最多 80 字；留白陣列表示一般 AI 模式
- `english_aliases`：每個關鍵字最多 3 個自訂英文替代詞；同組內任一原詞或別名命中即可
- `match: "any"`：OR，至少命中一組；`"all"`：AND，每組都要命中，可分別位於標題與摘要
- `exclude_keywords`：任何排除詞命中即排除；排除優先於包含
- `lookback_days`：1–30 天；每日設定預設 2 天，依收集時刻精確回溯 48 小時，不會悄悄放寬時間或主題來湊數。較長期間僅供另行指定的研究用途；每日流程仍須使用 2 天
- CLI 的 `--keyword`、`--exclude` 取代對應陣列；`--alias` 加入明確對應，`--match all`、`--lookback-days 14` 可覆寫其他值
- 使用 Unicode NFKC、casefold 與空白正規化；英文使用字詞邊界，`AI` 不會命中 `said` 或 `chain`；中文採原文子字串比對。片語不可跨標題/摘要邊界。不做語意推測、繁簡轉換、同義詞擴張或隱藏翻譯

### 網頁設定的實際作用

每期日報的「設定新聞關鍵字 / Configure news keywords」可編輯關鍵字、英文別名、排除詞、OR/AND 與回溯天數，立即預覽 JSON 並匯出 `topics.json`。下載後使用 `--topic-config`，或經一般 repo 審核流程更新 `daily/data/topics.json`。此靜態網站沒有設定後端：沒有全站自動儲存、沒有在瀏覽器執行新聞搜尋，也不會改變現有已發布期數。表單不儲存至 localStorage；重新載入會回復建置時設定。原有「搜尋本期 / Search this issue」只篩選本期內容，與新新聞收集分開。

### 來源、隱私與限制

- 只有在實際執行 collector 時，查詢詞才會透過 HTTPS 傳給所選公共搜尋服務。請勿輸入私人或機密資料；不要把私人設定提交到公開 repo
- [GDELT DOC API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/) 提供不需金鑰的新聞探索。它搜尋英文翻譯索引，因此中文主題應自行填入英文別名；缺少別名會記錄 `needs_english_alias`，不把不支援的查詢當作「沒有新聞」。搜尋先限制來源網域，再核對回傳的精確 HTTPS 網域
- [arXiv API](https://info.arxiv.org/help/api/user-manual.html) 提供論文中標題/摘要的實際查詢。資料不是一般新聞；首次投稿日期用於時間窗，更新日期另外保留。遵守[單連線、每三秒最多一次的限制](https://info.arxiv.org/help/api/tou.html)；請勿同時從多個程序/電腦執行收集
- GDELT 通常只回傳標題，所以本地相關性驗證只看其原始標題；固定 feeds 與 arXiv 也比對原始摘要。此保守篩選可能漏掉內文才提及主題的文章；不會抓全文、信任 HTML、執行來源指令，或用產生的中文翻譯冒充命中證據
- 搜尋最多讀取每個服務設定的結果上限，非全網搜尋或完整涵蓋率。查詢達到上限、部分主題缺少支援、429、逾時、非預期格式等狀態都保留在報告中；没有假裝成功的空清單。沒有自動重試或背景排程
- `daily/data/sources.json` 的 `search` 決定服務、單次上限（10–250）與新聞來源的精確網域允許清單。`topics.json` 不能改搜尋端點或新增來源權限；有意新增可信來源時，另外審核來源設定
- URL 去重僅移除 fragment 與 `utm_*`、`fbclid`、`gclid`、`mc_cid`、`mc_eid`；保留其他查詢參數，另以正規化後完全相同的標題排除明顯重複。不是語意事件聚類
- GDELT `seendate` 保留為 `provider_seen_at`，不冒充已確認發布日期；該類草稿的 `published_date` 留空，編輯須查原文補入日期

### 從搜尋到正式電子報

1. 檢查候選報告的 `search_status`、`searches`、`failures`、`coverage_warnings` 與來源。Collector 結束碼：0 有候選且搜尋流程完成；1 無候選；2 設定錯誤或主題搜尋失敗/部分完成。一般模式保留既有退出行為
2. 如果報告為 `partial`，先處理問題；確定接受目前範圍時才使用 `create_draft.py ... --allow-partial`。至少一個關鍵字搜尋服務必須成功；所有搜尋失敗時，連此參數也不能只拿固定 feed 結果冒充搜尋成功
3. 草稿只選相關、在時間窗內、不重複的候選，目標 10 則、最低 6 則。少於 6 則時拒絕建立草稿；不加無關文章、不補假新聞。草稿採 exclusive create，不覆寫既有檔案，也禁止直接寫入正式 `daily/data/issues/`
4. 草稿保留設定快照、實際查詢、來源 URL、抓取時間、原始標題/摘要及命中的詞。所有雙語編輯欄位留白，`reviewed` 為 false。請核對原文與作者，忠實濃縮、翻譯繁中/英文 title、summary、takeaway、caveat，不加入本刊觀點或建議；另填期刊 title、coverage、editorial_note。查證含時區的 `published_at` 與相符的 `published_date` 後，才把各則 `date_verification_required` 改為 false
5. 如果搜尋曾不完整，必須在兩種語言的 coverage/editorial_note 說明限制，並明確設定 `discovery.limitations_acknowledged: true`。最後人工核准 `reviewed: true` 與實際 `reviewed_on`，再把草稿移入 `daily/data/issues/YYYY-MM-DD.json`
6. 執行 build、Python 與 Node 檢查。網站和選用的 email renderer 都會重新驗證主題證據、排除詞、日期、雙語欄位與審核狀態。正式頁面、RSS/Atom、email preview 顯示主題或一般 AI 標籤。這些結構驗證不等於事實查核

沒有新增 LLM、付費 API、帳號、金鑰、排程、發布、訂閱或寄送動作；新功能接到既有人工審核/靜態產生流程。

## Local preparation and reviewed preview pipeline

新增 `scripts/newsletter/pipeline.py`，把收集、草稿、審核與預覽串成可續作的本機流程。產物必須放在 repo 外；不會修改已發布資料、排程、提交、部署或寄信。

```sh
# 一般 AI 模式：即時收集，建立待審草稿
python -B scripts/newsletter/pipeline.py prepare --general --run-dir /tmp/newsletter-run

# 關鍵字模式：使用明確設定的主題／英文別名
python -B scripts/newsletter/pipeline.py prepare --topic-config newsletter/examples/topics-embodied-ai.json --run-dir /tmp/newsletter-topic-run

# 查詢目前狀態，不連線、不重抓資料
python -B scripts/newsletter/pipeline.py status --run-dir /tmp/newsletter-run

# 如需接受已查明的部分來源範圍，以原候選快照續作；不會重送搜尋
python -B scripts/newsletter/pipeline.py prepare --run-dir /tmp/newsletter-topic-run --resume --allow-partial

# 人工完成 draft.json 的來源查證、雙語內容與審核欄位後，產生隔離預覽
python -B scripts/newsletter/pipeline.py preview --run-dir /tmp/newsletter-run

# 或用另外編輯好的檔案，避免改動原始草稿
python -B scripts/newsletter/pipeline.py preview --run-dir /tmp/newsletter-run --reviewed-issue /tmp/reviewed-newsletter.json
```

### 一個 run 的內容

- `run.json`：可讀狀態、錯誤、下一步相關資料與雜湊；`status` 指令會驗證輸入後顯示下一步
- `sources.json`、`topic.json`、`candidates.json`、`selection.json`：固定輸入快照，修改後拒絕續作；如需調整選題，保留現有編輯並用新的 run 目錄
- `draft.json`：可編輯的雙語草稿；重新 `prepare --resume` 不覆寫編輯、不重抓網路
- `EDITORIAL-CHECKLIST.txt`：來源查證與編輯核准步驟
- `reviewed-input.json`、`preview-manifest.json`：已驗證編輯版本與預覽檔案雜湊
- `preview/`：網站預覽，含日報頁面、存檔、來源 JSON、樣式與腳本；首頁是本機預覽導覽，不是正式網站首頁的替代品

只分享或在本機 HTTP server 開啟 `preview/`，不要把含候選資料的整個 run 目錄公開。若需要 HTTP 預覽，可使用 `python -m http.server 4173 --bind 127.0.0.1 --directory /tmp/newsletter-run/preview`。此指令只是手動預覽範例，pipeline 不會自行開啟服務。

### 狀態與安全界線

- `awaiting_editorial_review`：草稿建立成功，仍未完成日報；人工填寫所有双語欄位、查證日期並核准後才可 preview
- `blocked_collection`：來源／搜尋／設定／數量不足。失敗原因完整保留。只有至少一個主題搜尋成功時，才可能明確接受部分結果；全部搜尋失敗不能被固定 feed 結果掩蓋
- `blocked_review`：內容未完整審核、来源證據被改動、或其他品質檢查失敗；可修正 draft 後再跑 preview
- `preview_ready`：隔離的靜態預覽完成，尚未發布、寄信或啟用排程。相同輸入重跑會驗證並重用既有預覽；改過內容或預覽檔案則拒絕靜默覆寫
- 結束碼 0 表示已到待審草稿或可檢視預覽；2 表示需處理的阻擋。`review_required` 保留為 true，因為結構驗證不能取代事實與原創性查核

run 日期使用 Asia/Taipei 的曆日。`--date YYYY-MM-DD --candidates /path/report.json` 可離線重用同一台北日期的收集報告；不把昨天的候選報告冒充今天重新收集。時間窗以報告的收集時刻為上界，保留含時區的秒級界線，不把發布日期四捨五入成整天。候選不足 6 則仍拒絕草稿。一般 AI 模式採來源設定中的時間窗；主題模式採 topic 設定，每日設定均為 2 天。來源設定、主題、候選、選取證據与預覽來源都有雜湊檢查；這是本機一致性驗證，不是外部服務簽章或新聞真實性的證明。

審核版必須來自本次選取，可刪除至至少 6 則；不得換成其他 ID/URL、捏造命中或改寫原始來源證據。出版時間仍須人工核對，預覽要求含時區的 `published_at` 在原精確時間窗內；已確認的發布時刻不能被換成另一時刻。只有日期、更新時間或搜尋服務首次觀察時間，均不足以通過這項檢查。部分來源限制必須保留，且在兩種語言的 coverage/editorial_note 中說明，再設定 `limitations_acknowledged: true`。既有同日期正式期數不會被此流程替換；勘誤另走明確審核流程。

## Source discovery and readiness

The shipped collection profile is 48 hours in both general and keyword modes. Four existing feeds remain enabled. Four documented additions (arXiv machine learning, arXiv computation and language, CNA technology, and Martin Fowler) are configured with `enabled: false`; they have not been live-tested by this change. Disabled feeds perform no I/O and appear in `disabled_sources`, without a fabricated success or failure receipt. Enabled feeds have explicit receipts, and failed or malformed feeds remain visible as partial collection.

`feed_hosts` restricts the feed request; `article_hosts` independently restricts story links. Source metadata records family, region, language, attribution guidance and rights evidence, without certifying an individual byline or granting translation permission. The collector retains RSS/Atom/RDF bylines as unverified. A mixed-author feed can contain guests, quotations or link posts.

The CLI and pipeline read reviewed historical editions before selecting a draft. They exclude normalized previously published URLs and exact supplied `event_id` matches, keep tracking-parameter deduplication in general mode, and never fill a quota with excluded stories. This is conservative identity matching, not semantic event clustering. A changelog reusing its URL for a genuinely new dated event needs explicit editorial review outside this automatic selection; the collector does not silently waive the duplicate.

`daily/data/source-catalog.json` is a discovery catalog, not runtime feed activation. Google News Taiwan/Traditional Chinese and English headline pages, independent reporting, research, open-source releases, and identified engineering authors extend the editorial discovery routes. Google News is an aggregator: verify the original publisher, author, publication instant and source body, and deduplicate the event across outlets and prior editions. No undocumented Google News RSS/API or automatic headline scraper is enabled. See [Discovery sources and activation checks](../newsletter/DISCOVERY-SOURCES.md).

Run `python -B scripts/newsletter/source_config.py --check` for offline configuration/catalog checks. These checks do not verify live availability, licensing, factual support or popularity. New feed activation requires a separate bounded live check and normal reviewed configuration change; no background retry or subscription is installed.

預覽會強制停用 email 訂閱表單，即使來源 config 已啟用訂閱，避免本機預覽發出測試以外的請求。鎖住、被中斷、含符號連結或修改過固定輸入的 run 會保守停止；不會自動刪除使用者編輯或重送搜尋。來源頁面／資產／日報存檔變更後，需使用新的 run。

### 尚未啟用的整體每日流程

此版本完成本機串接與品質閘門，沒有自主撰寫雙語內容的模型介接，也沒有啟用每日觸發、遠端發布或 email 發送。新增 Kit 的離線設定檢查與停用中的訂閱表單轉交／草稿介面；仍需服務設定、寄件身分、隱私／同意流程與明確啟用授權。現有選用 email adapter 保持原狀且停用。任何排程或傳送整合都不得把 `awaiting_editorial_review` 當作可發佈狀態。

## Kit 離線準備

執行 `node scripts/newsletter/kit-readiness.mjs newsletter/examples/kit-config.example.json` 可查看缺少的設定，完全不會連線 Kit。預設關閉訂閱與草稿建立。詳見 [Kit 設定與授權界線](../newsletter/KIT-SETUP.md)。

Kit 模組只提供分語言的託管表單轉交與經精確核准的私人草稿介面：要求已查證的雙重確認／同意設定、明確語言分群、寄件者與模板；草稿固定 `public: false`、`send_at: null`。它不把訪問表單當作訂閱成功，也沒有寄送或公開發布功能。目前只有 mock transport 測試，未接帳號、未讀金鑰、未建立真實訂閱或 Kit 草稿。網站表單未改接 Kit。

## 雙語撰稿介面：離線契約

新增 `scripts/newsletter/writer.py prepare/apply`，可把原始待審選取與逐則原文／摘要整理成私人請求，並驗證另外提供的雙語 JSON 回覆。每一則需保留 ID、網址與來源證據，且雙語欄位必須附原文中的支持引句；引句本身不代表敘述已獲證實。產物仍是 `reviewed: false`，日期查證與來源限制確認完全保留人工閘門。

詳見 [離線 writer 操作與限制](../newsletter/WRITER-CONTRACT.md)。這不是已連線的 LLM：沒有實際模型呼叫或費用，provider/model/pricing 尚未選定；字數／回覆報告的 token 與自填價格上限不冒充真實帳單保證。所有 live 呼叫固定拒絕。請求與支持引句檔案只能放在 repo 外，並以僅擁有者可讀寫的權限建立；不要公開整個撰稿工作目錄。
# Headline-first daily reading (from 2026-10-07)

For a new enhanced edition, onboard its verified JPEGs and manifest entries before `pipeline prepare`, which snapshots the entire source set. If artwork is added after preparation, preserve the earlier run and start a new run with the saved candidate report. The old run rejects source drift; missing or invalid images leave its preview unwritten. This is a manual editorial/image preparation step, not automatic image generation.

The first two editorial picks are featured; remaining picks are smaller headline links. Titles open the original source. Full bilingual summaries, source highlights and caveats stay closed until requested. The native summary dialog supports Escape, backdrop dismissal, focus return and language changes. Without JavaScript, closed disclosure elements contain the same complete text. Supporting summary sources remain visible as links in the reading view, feeds and optional email previews. AI full translation is visibly disabled until source rights and a translation service are configured.

### Source-only summaries and reviewed length exceptions

From October 7, the ordinary target remains 450–550 non-whitespace Unicode code points. Summaries, titles, highlights and caveats must faithfully condense identified sources; source authors' opinions require attribution. Do not add newsletter analysis, suggested tests, reader advice or unsupported implications, even under an editorial label. Keep acquisition limitations in the issue disclosure or review record.

If source-use limits or verified source scope cannot support the target, a human may approve a shorter summary using `summary_length_exception`. Both Python and JavaScript require the supported reason, actual count, review date and SHA-256 binding to the exact issue date, item ID, original URL, ordered `summary_sources` and all eight bilingual text fields. An edited translation, title, highlight, caveat or source list invalidates the exception. Empty, overlong, unreviewed, stale or unnecessary exceptions fail validation. The earlier October 6 policy is unchanged.

This record does not itself prove factual support or copyright permission. Reviewers must read the sources, check every claim in both languages and respect shared source-use limits. The writer adapter cannot mint an exception or mark output reviewed; insufficient material still returns `insufficient_evidence`. The October 7 correction retains its original publication date and IDs, while Git history preserves the earlier wording.

Supplemental summary links use an explicit absolute HTTPS grammar: ASCII DNS labels (or a punycode hostname), at most 63 characters per label and 253 per hostname, with an alphabetic start to the final label. Numeric/IP authorities, malformed or automatically repaired URLs, credentials, nonstandard ports, whitespace and malformed Unicode are rejected. The URL limit is 2,000 Unicode code points, shared by the build, optional email adapter and browser reader.

Seven layouts follow the issue's Taipei calendar date, Monday through Sunday, independently of the three color palettes. The layout selector previews all seven without changing the edition date or editorial order. October 4 and October 6 keep their original presentation.

The archive has a separate all-history content search. Its generated index contains all validated release editions, including both languages, summaries, takeaways, caveats, sources and topic keywords. It has no date window and is independent of the date-based edition browser. It does not fetch or imply access to external full articles. Index loading failures remain visible.

Before building, install the pinned image validator with `python -m pip install -r scripts/newsletter/requirements.txt`. Each enhanced pick must have a story-ID-bound entry in `daily/data/image-manifest.json`, bilingual alt/caption/credit, matching source URL and SHA-256, and a local JPEG. The builder decodes and checks the files before writing any output: at most 300 KiB per image, 2048 pixels per side, and 2 MiB per edition. Image URLs and symlinks are rejected. The browser keeps a 16:9 frame for images and failures. Archived original generation files are not served.

`python -B tests/newsletter/browser_check.py --output /tmp/newsletter-browser-evidence` is the portable CI suite. It checks all 7 layouts × 2 languages × 4 widths, every summary, keyboard controls, historical search, no-JavaScript reading and image failures. Unit/mock-DOM tests do not count as browser evidence. The existing isolated pipeline snapshots JPEGs and the image validator as well as page sources; it never publishes them.
