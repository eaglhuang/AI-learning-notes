#!/usr/bin/env python3
"""Deterministic static newsletter builder. Never fetches, publishes or sends mail."""
import argparse
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
import json
import os
from pathlib import Path
import sys
from xml.etree import ElementTree as ET
from edition import CATEGORIES, LOCALES, load_edition
from topics import load_topic, validate_topic

ROOT = Path(__file__).resolve().parents[2]


def esc(value):
    return escape(str(value), quote=True)


def t(zh, en, locale="zh-TW"):
    return f'<span data-zh="{esc(zh)}" data-en="{esc(en)}">{esc(en if locale == "en" else zh)}</span>'


def translated(value, locale):
    return t(value["zh-TW"], value["en"], locale)


def relative(target, page):
    return os.path.relpath(target, str(Path(page).parent)).replace(os.sep, "/")


def layout(body, *, page, locale, config, title, theme="citrus", alternate=None, enhanced=False):
    asset = lambda path: relative("daily/" + path, page)
    home = relative("index.html", page)
    alt = alternate or ("daily/en/index.html" if locale == "zh-TW" else "daily/index.html")
    canonical = config["site_url"] + "/" + page.removesuffix("index.html")
    extra_css = f'<link rel="stylesheet" href="{asset("weekly-layouts.css")}">' if enhanced else ''
    return f'''<!doctype html>
<html lang="{locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · {esc(config['title'][locale])}</title>
<meta name="description" content="{esc('原創雙語 AI 新聞、論文與工具選讀。每期保留來源、日期與限制。' if locale == 'zh-TW' else 'Bilingual AI reading picks with original summaries, sources, dates and caveats.')}">
<link rel="canonical" href="{esc(canonical)}"><link rel="alternate" hreflang="{'en' if locale == 'zh-TW' else 'zh-TW'}" href="{esc(config['site_url'] + '/' + alt.removesuffix('index.html'))}">
<link rel="alternate" type="application/rss+xml" title="AI Daily RSS" href="{asset('feed-en.xml' if locale == 'en' else 'feed.xml')}">
<link rel="alternate" type="application/atom+xml" title="AI Daily Atom" href="{asset('atom-en.xml' if locale == 'en' else 'atom.xml')}">
<link rel="stylesheet" href="{asset('daily.css')}">{extra_css}<script src="{asset('daily.mjs')}" type="module"></script></head>
<body class="{theme}" data-default-locale="{locale}"><a class="skip" href="#content">{t('跳至內容','Skip to content',locale)}</a>
<header><a class="brand" href="{asset('en/index.html' if locale=='en' else 'index.html')}" data-local-link><span class="mark" aria-hidden="true">a↗</span><span>{translated(config['title'],locale)}<small>by Eagl Huang / Learning Notes</small></span></a>
<nav aria-label="Main"><a href="{asset('archive/en/index.html' if locale=='en' else 'archive/index.html')}" data-local-link>{t('歷期日報','Archive',locale)}</a><a href="#subscribe">{t('訂閱','Subscribe',locale)}</a><a class="language" id="language" href="{relative(alt,page)}" lang="{'en' if locale == 'zh-TW' else 'zh-TW'}">EN ↔ 繁中</a></nav></header>
<main id="content">{body}</main><footer><a href="{home}">← AI Learning Notes</a><span>{t('原創摘要與選讀。來源著作權歸原作者。','Original summaries. Sources belong to their respective authors.',locale)}</span><a href="#content">↑ {t('回頂端','Back to top',locale)}</a></footer></body></html>\n'''


def subscription(config, page, locale):
    settings = config["subscription"]
    enabled = settings.get("enabled") is True
    if enabled:
        from validate_issue import _url_key
        for field in ("endpoint", "privacy_url"):
            _url_key(settings.get(field))
        if not settings.get("provider"):
            raise ValueError("enabled email service must identify its provider")
    feed = relative("daily/feed.xml", page)
    feed_en = relative("daily/feed-en.xml", page)
    atom = relative("daily/atom.xml", page)
    form = ''
    if enabled:
        form = f'''<form id="subscription" data-endpoint="{esc(settings['endpoint'])}"><label for="email">{t('電子郵件','Email address',locale)}</label><input id="email" type="email" name="email" autocomplete="email" maxlength="254" required placeholder="you@example.com"><label class="consent"><input type="checkbox" name="consent" required>{t('我同意接收每日摘要，可隨時退訂。','I agree to receive daily summaries and can unsubscribe anytime.',locale)}</label><label class="trap" aria-hidden="true">Website<input name="website" tabindex="-1" autocomplete="off"></label><p>{esc(settings['provider'])} · <a href="{esc(settings['privacy_url'])}">{t('隱私說明','Privacy notice',locale)}</a></p><button type="submit" disabled>{t('傳送確認信','Send confirmation email',locale)}</button><noscript>{t('請開啟 JavaScript 後使用雙重確認訂閱。','Enable JavaScript to request a double opt-in email.',locale)}</noscript><p id="subscription-status" role="status" aria-live="polite"></p></form>'''
    else:
        form = f'''<div class="email-pending"><span class="status-dot"></span><strong>{t('Email 訂閱準備中','Email subscription coming next',locale)}</strong><p>{t('寄信服務尚未連接，目前不收集信箱。完成設定後，這裡會提供確認信與退訂功能。','The email service is not connected, so no addresses are collected. Confirmation and unsubscribe will be available after setup.',locale)}</p><a href="{relative('daily/README.md',page)}">{t('查看功能與設定狀態','View functionality and setup status',locale)} ↗</a></div>'''
    return f'''<section id="subscribe" class="subscribe"><div><span class="eyebrow">LESS SCROLL. MORE SPARK.</span><h2>{t('讓好想法，持續生長。','Let good ideas keep growing.',locale)}</h2><p>{t('用閱讀器訂閱已發布日報；每一篇都有獨立網址。','Follow published editions in your feed reader. Every issue has its own permanent link.',locale)}</p><div class="feed-links"><a href="{feed}">RSS 繁中 ↗</a><a href="{feed_en}">RSS English ↗</a><a href="{atom}">Atom ↗</a></div></div>{form}</section>'''


def topic_label(issue, locale):
    topic = issue.get('topic', {})
    if not topic.get('keywords'):
        return 'General AI edition' if locale == 'en' else '一般 AI 選讀'
    return ('Topic edition: ' if locale == 'en' else '關鍵字專題：') + ' / '.join(topic['keywords']) + (' · AND' if topic.get('match')=='all' else ' · OR')


def topic_settings(config, page, locale, localized=False):
    tr = lambda zh,en: t(zh,en,locale)
    topic = config.get('topic_settings', validate_topic())
    keywords = '\n'.join(topic['keywords'])
    aliases = '\n'.join(key+'='+'|'.join(values) for key,values in topic['english_aliases'].items())
    exclusions = '\n'.join(topic['exclude_keywords'])
    options = ''.join(f'<option value="{key}" {"selected" if topic["match"]==key else ""}>{zh}</option>' for key,zh in [('any','OR / 任一關鍵字'),('all','AND / 全部關鍵字')])
    if localized:
        options = ''.join(f'<option value="{key}" {"selected" if topic["match"]==key else ""} data-zh="{zh}" data-en="{en}">{en if locale=="en" else zh}</option>' for key,zh,en in [('any','OR / 任一關鍵字','OR / Any keyword'),('all','AND / 全部關鍵字','AND / All keywords')])
    return f'''<section class="topic-settings"><details id="topic-settings"><summary>{tr('設定新聞關鍵字','Configure news keywords')}</summary>
<p>{tr('匯出設定後，執行收集程式才會搜尋新新聞。這裡只預覽設定，不會儲存到伺服器，也不會改變已發布日報。','Export the settings, then run the collector to discover new articles. This page only previews configuration; it does not save server settings or change published editions.')}</p>
<p>{tr('執行搜尋會把關鍵字傳給 GDELT 與 arXiv，請勿輸入私人資訊。GDELT 使用英文索引；中文主題請自行填入英文別名。','Running a search sends keywords to GDELT and arXiv. Do not enter private information. GDELT uses an English index; supply your own English aliases for Chinese topics.')}</p>
<form id="topic-settings-form" class="js-only">
<label for="topic-keywords">{tr('關鍵字，每行一個；留白使用一般 AI 模式','Keywords, one per line; leave empty for general AI mode')}</label><textarea id="topic-keywords" name="keywords" rows="3" maxlength="648">{esc(keywords)}</textarea>
<label for="topic-aliases">{tr('英文別名，例如：具身智能=embodied AI|embodied intelligence','English aliases, e.g. 具身智能=embodied AI|embodied intelligence')}</label><textarea id="topic-aliases" name="aliases" rows="2" maxlength="2700">{esc(aliases)}</textarea>
<label for="topic-exclusions">{tr('排除詞，每行一個','Exclusions, one per line')}</label><textarea id="topic-exclusions" name="exclusions" rows="2" maxlength="648">{esc(exclusions)}</textarea>
<div class="topic-options"><label for="topic-match">{tr('比對方式','Matching')}</label><select id="topic-match" name="match">{options}</select><label for="topic-days">{tr('回溯天數（1–30）','Lookback days (1–30)')}</label><input id="topic-days" name="days" type="number" min="1" max="30" value="{topic['lookback_days']}" required></div>
<button type="submit">{tr('匯出 topics.json','Export topics.json')}</button><button type="reset">{tr('還原表單','Reset form')}</button><p id="topic-settings-status" role="status" aria-live="polite"></p><pre id="topic-config-preview" aria-label="Local topic configuration"></pre></form>
<p><a href="{relative('daily/README.md',page)}#keyword-topics">{tr('查看執行方式與搜尋限制','Read setup instructions and search limitations')} ↗</a></p></details></section>'''


def enhanced_date(config, issue_date):
    policy = config.get('enhanced_ui')
    if policy is None:
        return False
    start = date.fromisoformat(policy['effective_from'])
    return date.fromisoformat(issue_date) >= start


def script_json(value):
    text = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    for char in ('<', '>', '&', '\u2028', '\u2029'):
        text = text.replace(char, '\\u'+format(ord(char), '04x'))
    return text


def search_index(issues, config):
    rows = []
    for issue in issues:
        for item in issue['items']:
            rows.append({
                'key': issue['date']+':'+item['id'], 'storyId': item['id'],
                'editionDate': issue['date'], 'sourcePublishedDate': item['published_date'],
                'category': item['category'], 'source': item['source'], 'sourceUrl': item['source_url'],
                'localized': {l: {k: item[l][k] for k in ('title', 'summary', 'takeaway', 'caveat')} for l in LOCALES},
                'editionTitle': issue['title'],
                'summarySources': item.get('summary_sources', []),
                'shortSummaryReason': item.get('summary_length_exception', {}).get('reason'),
                'sourceOnly': item.get('source_check', {}).get('summary_mode') == 'source_only_translated_condensation',
                'keywords': issue.get('topic', {}).get('keywords', []),
                'aliases': issue.get('topic', {}).get('english_aliases', {}),
                'permalink': {l: config['site_url']+'/daily/'+issue['date']+('/en/' if l == 'en' else '/')+'#'+item['id'] for l in LOCALES}
            })
    return {'schemaVersion': 1, 'scope': 'published-newsletter-content',
            'editions': [i['date'] for i in issues], 'records': rows}


def summary_dialog(locale, weekday=None):
    picker = ''
    if weekday is not None:
        options = ''.join(f'<option value="{n}" {"selected" if n==weekday else ""} data-zh="週{zh}" data-en="{en}">{en if locale=="en" else "週"+zh}</option>' for n,(zh,en) in enumerate(zip('一二三四五六日',('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'))))
        picker = f'<label class="dialog-layout" for="dialog-layout">{t("版型","Layout",locale)} <select id="dialog-layout">{options}</select></label>'
    return f'''<dialog id="summary-dialog" class="summary-dialog" aria-labelledby="summary-title"><div class="dialog-controls"><button type="button" data-dialog-language>{t('切換為 English','切換為繁體中文',locale)}</button><button type="button" data-dialog-close autofocus>{t('關閉摘要','Close summary',locale)} ✕</button></div>{picker}<p data-dialog-meta></p><h2 id="summary-title"></h2><p class="summary-body" data-dialog-summary></p><p data-dialog-length-note hidden></p><h3 data-dialog-highlight-label>{t('原文重點','Source highlight',locale)}</h3><p data-dialog-takeaway></p><h3>{t('限制與日期說明','Caveats & dates',locale)}</h3><p data-dialog-caveat></p><h3 data-dialog-sources-label hidden></h3><ul data-dialog-sources></ul><a data-dialog-source target="_blank" rel="noopener noreferrer">{t('閱讀原文','Original source',locale)} ↗</a></dialog>'''


def enhanced_card(item, i, config, page, locale, permalink, search):
    tr = lambda zh, en: t(zh, en, locale)
    field = lambda name: tr(item['zh-TW'][name], item['en'][name])
    image = config['_images'][item['id']]
    caption = translated(image['caption'], locale)
    license_credit = ''
    image_kind = 'ai-illustration' if image['ai_generated'] else 'licensed-source'
    fallback = tr('示意圖暫時無法顯示','Illustration unavailable') if image['ai_generated'] else tr('原文圖片暫時無法顯示','Source image unavailable')
    if not image['ai_generated']:
        license = image['license']
        links = ((license['image_url'],'原始圖片','Source image'),
                 (license['source_url'],'來源授權','Source license'),
                 (relative(license['license_path'],page),'授權全文','License text'),
                 (relative(license['notice_path'],page),'修改說明','Modification notice'))
        license_credit = '<p class="image-credit">'+translated(image['credit'],locale)+'<br>'+ ' · '.join(
            f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{tr(zh,en)}</a>' for url,zh,en in links)+'</p>'
    alt = image['alt']
    image_url = relative(image['path'], page)
    key = config['_issue_date']+':'+item['id']
    source_only = item.get('source_check', {}).get('summary_mode') == 'source_only_translated_condensation'
    highlight = tr('原文重點','Source highlight') if source_only else tr('實作啟示','Takeaway')
    length_note = ('<p>'+tr('本則採較短摘要：以已核對的原文內容與摘要使用範圍為限。','Shorter summary: limited to verified source material and permitted condensation.')+'</p>') if item.get('summary_length_exception') else ''
    source_links = ''.join(f'<li><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a></li>' for url in item.get('summary_sources', []))
    sources = ('<strong>'+tr('摘要來源','Summary sources')+'</strong><ul>'+source_links+'</ul>') if source_links else ''
    return f'''<article class="headline-story {'featured-story' if i < 2 else 'compact-story'}" id="{item['id']}" data-card data-category="{item['category']}" data-search="{esc(search)}"><figure><div class="story-image"><img src="{image_url}" width="{image['width']}" height="{image['height']}" loading="{'eager' if i < 2 else 'lazy'}" decoding="async" alt="{esc(alt[locale])}" data-alt-zh="{esc(alt['zh-TW'])}" data-alt-en="{esc(alt['en'])}"><span class="image-fallback" hidden>{fallback}</span></div><figcaption data-image-kind="{image_kind}">{caption}{license_credit}</figcaption></figure><div class="headline-copy"><div class="story-top"><span class="category">{tr(*CATEGORIES[item['category']])}</span><span class="number">{i+1:02d}</span></div><h3><a href="{esc(item['source_url'])}" target="_blank" rel="noopener noreferrer">{field('title')} ↗</a></h3><p class="headline-meta">{esc(item['source'])} · <time datetime="{item['published_date']}">{item['published_date']}</time></p><div class="story-actions"><button class="dialog-trigger" type="button" data-summary-key="{esc(key)}" aria-haspopup="dialog">{tr('閱讀摘要','Read summary')}</button><button type="button" disabled title="{esc('尚未啟用：需要核對全文使用權限並設定翻譯服務' if locale=='zh-TW' else 'Not enabled: full-text rights and a translation service must be configured')}" data-title-zh="尚未啟用：需要核對全文使用權限並設定翻譯服務" data-title-en="Not enabled: full-text rights and a translation service must be configured">{tr('AI 全文翻譯・尚未啟用','AI full translation · Not enabled')}</button></div><details class="summary-fallback"><summary>{tr('閱讀完整摘要','Read the full summary')}</summary><p>{field('summary')}</p>{length_note}<strong>{highlight}</strong><p>{field('takeaway')}</p><strong>{tr('限制與日期說明','Caveats & dates')}</strong><p>{field('caveat')}</p>{sources}</details><a class="permalink" href="{esc(permalink)}" data-local-link>{tr('這則的固定連結','Link to this pick')} ↗</a></div></article>'''


def render_issue(issue, issues, config, page, locale):
    tr = lambda zh,en: t(zh,en,locale)
    asset = lambda path: relative("daily/" + path, page)
    edition_path = lambda issue_date: issue_date+('/en/index.html' if locale=='en' else '/index.html')
    archive_path = 'archive/en/index.html' if locale=='en' else 'archive/index.html'
    theme = config["themes"][date.fromisoformat(issue["date"]).toordinal() % len(config["themes"])]
    count = len(issue["items"])
    enhanced = enhanced_date(config, issue['date'])
    if enhanced:
        config = dict(config, _issue_date=issue['date'])
        if '_images' not in config:
            from image_policy import load_images
            config['_images'] = load_images(ROOT, issue['items'])
    cards = []
    for i, item in enumerate(issue["items"]):
        field = lambda name: t(item['zh-TW'][name],item['en'][name],locale)
        category = CATEGORIES[item['category']]
        date_note = item.get('event_date')
        event = f'<p>{tr("事件／版本日期", "Event / version date")}: {esc(date_note)}</p>' if date_note and date_note != item['published_date'] else ''
        search = json.dumps({l: ' '.join([item[l][k] for k in ('title','summary','takeaway')])+ ' '+item['source'] for l in LOCALES},ensure_ascii=False)
        permalink = config['site_url']+'/daily/'+issue['date']+('/en/' if locale=='en' else '/')+'#'+item['id']
        if enhanced:
            cards.append(enhanced_card(item, i, config, page, locale, permalink, search))
            continue
        cards.append(f'''<article class="story story-{i}" id="{item['id']}" data-card data-category="{item['category']}" data-search="{esc(search)}"><div class="story-top"><span class="category">{tr(*category)}</span><span class="number">{i+1:02d}</span></div><h3><a href="#{item['id']}">{field('title')}</a></h3><p>{field('summary')}</p><div class="takeaway"><strong>{tr('實作啟示','Try this')}</strong><p>{field('takeaway')}</p></div><details class="caveat"><summary>{tr('限制與日期說明','Caveats & dates')}</summary><p>{field('caveat')}</p>{event}</details><div class="source"><span>{esc(item['source'])}<br>{tr('發布','Published')} <time datetime="{item['published_date']}">{item['published_date']}</time></span><a href="{esc(item['source_url'])}" target="_blank" rel="noopener noreferrer">{tr('讀原文','Source')} ↗</a></div><a class="permalink" href="{esc(permalink)}">{tr('這則的固定連結','Link to this pick')} ↗</a></article>''')
    options = ''.join(f'<option value="{asset(edition_path(x["date"]))}" {"selected" if x["date"]==issue["date"] else ""}>{x["date"]}</option>' for x in issues)
    filters = ''.join(f'<button type="button" data-filter="{key}" aria-pressed="{str(key=="all").lower()}">{tr(*label)}</button>' for key,label in [('all',('全部','All'))]+list(CATEGORIES.items()))
    index = [x['date'] for x in issues].index(issue['date'])
    adjacent = []
    for offset, zh, en in [(-1,'較新一期','Newer issue'),(1,'較舊一期','Older issue')]:
        n=index+offset
        if 0 <= n < len(issues):
            adjacent.append(f'<a href="{asset(edition_path(issues[n]["date"]))}" data-local-link>{tr(zh,en)}: {issues[n]["date"]} ↗</a>')
    body = f'''<div class="edition"><span>VOL. {len(issues)-index:03d} / {issue['date'].replace('-','.')}</span><span>{tr('原文核對 · 原創雙語選讀','SOURCE-CHECKED · BILINGUAL READING PICKS')}</span></div>
<section class="hero"><div><div class="eyebrow">ATOMIC NOTES / DAILY CULTURE</div><h1>{tr('今天的 AI，','Today’s AI,')}<br><em>{tr('值得你多看一眼。','worth a second look.')}</em></h1><p>{translated(issue['title'],locale)}</p><a class="cta" href="#stories">{tr('探索本期','Explore this issue')} <span>↓</span></a></div><div class="orb" aria-hidden="true"><div class="orbit"></div><span class="cell">◉</span><span class="sticker">GROW<br>IDEAS.</span><small>CAPSULE → SIGNAL → GROWTH</small></div></section>
<p class="topic-label">{t(topic_label(issue,'zh-TW'),topic_label(issue,'en'),locale)}</p><div class="notice">{translated(issue['coverage'],locale)}</div><p class="editorial-note">{translated(issue['editorial_note'],locale)}</p>
<div class="issue-navigation"><label class="js-only" for="issue-date">{tr('選擇日期','Choose an issue')}</label><select class="js-only" id="issue-date">{options}</select><a href="{asset(archive_path)}" data-local-link>{tr('所有期數','All editions')} ↗</a><a href="{asset('data/issues/'+issue['date']+'.json')}" download>{tr('下載 JSON','Download JSON')}</a><button class="js-only" id="print-issue" type="button">{tr('列印 / PDF','Print / PDF')}</button></div>
<section class="toolbar" aria-label="Story filters"><h2>{tr('今日的靈感清單','Your daily signal')}</h2><div class="filters js-only">{filters}</div></section>
<div class="search-row js-only"><label for="search">{tr('搜尋本期','Search this issue')}</label><input type="search" id="search" placeholder="{esc('標題、摘要或來源' if locale=='zh-TW' else 'Title, summary or source')}" data-placeholder-zh="標題、摘要或來源" data-placeholder-en="Title, summary or source"><button type="button" id="clear-filters">{tr('重設','Reset')}</button><span id="result-count" role="status" aria-live="polite">{count} / {count}</span></div>
<p id="empty-state" hidden>{tr('找不到符合的內容。試試其他關鍵字或重設篩選。','No matching picks. Try another keyword or reset the filters.')}</p><div id="stories" class="stories">{''.join(cards)}</div>
{topic_settings(config,page,locale,localized=enhanced)}{subscription(config,page,locale)}<section class="next"><span>{tr('每天換個視角。','A different perspective, every day.')}</span><div>{''.join(adjacent)}<a href="{asset(archive_path)}" data-local-link>{tr('日報存檔','Issue archive')} ↗</a></div></section>'''
    alternate = 'daily/'+issue['date']+('/en/index.html' if locale=='zh-TW' else '/index.html')
    if enhanced:
        weekday = date.fromisoformat(issue['date']).weekday()
        names = [('一・雙欄焦點','Mon · Paired focus'),('二・橫向報導','Tue · Feature rows'),('三・編輯桌','Wed · Editorial desk'),('四・筆記欄','Thu · Notebook'),('五・看板','Fri · Bulletin'),('六・週末閱讀','Sat · Weekend reading'),('日・週日專刊','Sun · Sunday journal')]
        options = ''.join(f'<option value="{n}" {"selected" if n==weekday else ""} data-zh="週{zh}" data-en="{en}">{esc(en if locale=="en" else "週"+zh)}</option>' for n,(zh,en) in enumerate(names))
        picker = f'<div class="layout-picker js-only"><label for="weekday-layout">{tr("切換版型（期別日期不變）","Change layout (edition date stays the same)")}</label><select id="weekday-layout">{options}</select></div>'
        body = body.replace('<div id="stories" class="stories">', picker+'<div id="stories" class="headline-grid">')
        body = f'<div class="enhanced-issue" data-edition-date="{issue["date"]}" data-weekday="{weekday}">{body}</div>'+summary_dialog(locale,weekday)+f'<script type="application/json" id="issue-content">{script_json(search_index([issue],config))}</script>'
    return layout(body,page=page,locale=locale,config=config,title=issue['date'],theme=theme,alternate=alternate,enhanced=enhanced)


def render_archive(issues, config, page, locale):
    tr=lambda zh,en:t(zh,en,locale)
    cards=[]
    for issue in issues:
        data={l:' '.join([issue['title'][l],issue['date']]+[i[l]['title']+' '+i['source'] for i in issue['items']]) for l in LOCALES}
        url=relative('daily/'+issue['date']+('/en/index.html' if locale=='en' else '/index.html'),page)
        cards.append(f'<article class="archive-card" data-card data-date="{issue["date"]}" data-category="all" data-search="{esc(json.dumps(data,ensure_ascii=False))}"><span class="eyebrow">{issue["date"]} / {len(issue["items"])} {tr("則選讀","picks")}</span><h2><a href="{url}" data-local-link>{translated(issue["title"],locale)} ↗</a></h2><p>{translated(issue["coverage"],locale)}</p><a href="{url}" data-local-link>{tr("閱讀本期","Read the issue")} →</a></article>')
    body=f'''<div class="edition"><span>THE READING ROOM</span><span>{len(issues)} {tr('期正式日報','published edition(s)')}</span></div><section class="archive-hero"><span class="eyebrow">SMALL IDEAS. LASTING CONNECTIONS.</span><h1>{tr('把靈感，','Keep your ideas,')}<br><em>{tr('留在這裡。','right here.')}</em></h1><p>{tr('日報專屬存檔，與技術長文分開。只有真正發布的選讀，沒有假歷史期數。','A dedicated newsletter archive, separate from technical essays. Real editions only.')}</p></section><div class="search-row js-only"><label for="search">{tr('搜尋歷期','Search editions')}</label><input id="search" type="search"><label for="archive-date">{tr('日期','Date')}</label><input id="archive-date" type="date"><button id="clear-filters" type="button">{tr('重設','Reset')}</button><span id="result-count" role="status" aria-live="polite"></span></div><p id="empty-state" hidden>{tr('這個日期或關鍵字尚無日報。請重設篩選查看全部。','No edition matches this date or keyword. Reset to see all editions.')}</p><div class="archive-grid">{''.join(cards)}</div>{subscription(config,page,locale)}'''
    panel = f'<section class="archive-search-panel" id="all-history-search" data-index-url="{relative("daily/data/search-index.json",page)}"><h2>{tr("搜尋所有電子報內容","Search all newsletter content")}</h2><p>{tr("開啟 JavaScript 後可跨期搜尋；也可使用下方日期瀏覽與閱讀各期。","Enable JavaScript to search all editions, or browse and read individual issues below.")}</p></section>'
    body = body.replace('<div class="search-row js-only">', panel+'<h2>'+tr('按期瀏覽','Browse by edition')+'</h2><div class="search-row js-only">', 1)
    return layout(body+summary_dialog(locale),page=page,locale=locale,config=config,title='Archive',alternate='daily/archive/'+('en/index.html' if locale=='zh-TW' else 'index.html'),enhanced=True)


def feeds(issues,config,locale,atom=False):
    site=config['site_url']+'/daily/'
    suffix='-en' if locale=='en' else ''
    def story_text(item):
        text = item[locale]['title']+': '+item[locale]['summary']
        if item.get('summary_length_exception'):
            text += '\n'+('Shorter source-limited summary.' if locale=='en' else '本則依來源範圍採較短摘要。')
        if item.get('summary_sources'):
            text += '\n'+('Summary sources: ' if locale=='en' else '摘要來源：')+' '.join(item['summary_sources'])
        return text
    def url(issue): return site+issue['date']+('/en/' if locale=='en' else '/')
    if atom:
        ns='http://www.w3.org/2005/Atom'; ET.register_namespace('',ns)
        tag=lambda s:f'{{{ns}}}{s}'
        root=ET.Element(tag('feed'),{'{http://www.w3.org/XML/1998/namespace}lang':locale})
        for key,val in [('id',site),('title',config['title'][locale]),('updated',issues[0]['date']+'T12:00:00+08:00')]:ET.SubElement(root,tag(key)).text=val
        ET.SubElement(root,tag('link'),href=site+'atom'+suffix+'.xml',rel='self')
        ET.SubElement(root,tag('link'),href=site)
        author=ET.SubElement(root,tag('author'));ET.SubElement(author,tag('name')).text='Eagl Huang'
        for issue in issues:
            entry=ET.SubElement(root,tag('entry'))
            for key,val in [('id',url(issue)),('title',issue['title'][locale]),('updated',issue['date']+'T12:00:00+08:00'),('summary','\n\n'.join(story_text(i) for i in issue['items']))]:ET.SubElement(entry,tag(key)).text=val
            ET.SubElement(entry,tag('link'),href=url(issue))
            ET.SubElement(entry,tag('category'),term=topic_label(issue,locale))
    else:
        root=ET.Element('rss',version='2.0');channel=ET.SubElement(root,'channel')
        for key,val in [('title',config['title'][locale]),('link',site),('description','Original bilingual AI reading picks'),('language',locale)]:ET.SubElement(channel,key).text=val
        for issue in issues:
            item=ET.SubElement(channel,'item')
            ET.SubElement(item,'category').text=topic_label(issue,locale)
            dt=datetime.fromisoformat(issue['date']+'T12:00:00+08:00')
            for key,val in [('title',issue['title'][locale]),('link',url(issue)),('guid',url(issue)),('pubDate',format_datetime(dt)),('description','\n\n'.join(story_text(i) for i in issue['items']))]:ET.SubElement(item,key).text=val
    ET.indent(root,space='  ')
    return '<?xml version="1.0" encoding="utf-8"?>\n'+ET.tostring(root,encoding='unicode')+'\n'


def outputs(root=ROOT):
    config=json.loads((root/'daily/config.json').read_text(encoding='utf-8'))
    config['topic_settings']=load_topic(root/'daily/data/topics.json')
    from validate_issue import _url_key
    _url_key(config['site_url'])
    if not config.get('themes') or any(t not in ('citrus','electric','rose') for t in config['themes']):raise ValueError('invalid theme palette')
    issues=sorted([load_edition(p) for p in (root/'daily/data/issues').glob('*.json')],key=lambda x:x['date'],reverse=True)
    if not issues: raise ValueError('no reviewed real editions; refusing to generate a fake archive')
    enhanced_issues = [issue for issue in issues if enhanced_date(config, issue['date'])]
    if enhanced_issues:
        from image_policy import load_images
        config['_images'] = {}
        for issue in enhanced_issues:
            config['_images'].update(load_images(root, issue['items']))
    result={}
    for locale in LOCALES:
        sub='en/' if locale=='en' else ''
        for issue in issues:
            path=f'daily/{issue["date"]}/{sub}index.html';result[path]=render_issue(issue,issues,config,path,locale)
        path=f'daily/{sub}index.html';result[path]=render_issue(issues[0],issues,config,path,locale)
        path=f'daily/archive/{sub}index.html';result[path]=render_archive(issues,config,path,locale)
        suffix='-en' if locale=='en' else ''
        result[f'daily/feed{suffix}.xml']=feeds(issues,config,locale)
        result[f'daily/atom{suffix}.xml']=feeds(issues,config,locale,atom=True)
    result['daily/editions.json']=json.dumps([{'date':i['date'],'title':i['title'],'count':len(i['items']),'topic':i.get('topic',validate_topic())} for i in issues],ensure_ascii=False,indent=2)+'\n'
    result['daily/data/search-index.json'] = json.dumps(search_index(issues,config),ensure_ascii=False,indent=2)+'\n'
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    try: result=outputs()
    except (ValueError,KeyError,TypeError,OSError) as error:print(f'BUILD BLOCKED: {error}',file=sys.stderr);return 1
    drift=[]
    for name,content in result.items():
        path=ROOT/name
        if not path.exists() or path.read_text(encoding='utf-8')!=content:
            drift.append(name)
            if not args.check:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content,encoding='utf-8',newline='\n')
    if args.check and drift:print('Generated files are stale: '+', '.join(drift),file=sys.stderr);return 1
    print(f'{len(result)} static outputs verified; {len(drift)} '+('stale' if args.check else 'updated'))
    return 0


if __name__=='__main__':sys.exit(main())
