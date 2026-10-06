#!/usr/bin/env python3
"""Fetch bounded primary-source RSS/Atom candidates, never publish or translate."""
import argparse
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from xml.etree import ElementTree as ET
from validate_issue import _url_key, _unique_object
from topics import validate_topic, load_topic, match_topic, safe_url, normalized
from discovery import search_plan, parse_gdelt, dedup_key

ROOT=Path(__file__).resolve().parents[2]
MAX_BYTES=2_000_000


class PlainText(HTMLParser):
    def __init__(self): super().__init__();self.parts=[]
    def handle_data(self,data): self.parts.append(data)


def strip_markup(value):
    parser=PlainText();parser.feed(value or '')
    return ' '.join(' '.join(parser.parts).split())[:1800]


def parse_date(value):
    try:
        try: result=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:result=parsedate_to_datetime(value)
        return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError):return None


def parse_feed(content, source, now, days=7):
    if len(content)>MAX_BYTES:raise ValueError('oversized XML')
    # Decode before inspection. Byte substring checks alone miss UTF-16 entities.
    text=content.decode('utf-8-sig')
    if '\x00' in text or '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise ValueError('unsafe XML')
    declaration=re.match(r'\s*<\?xml[^>]*encoding=["\x27]([^"\x27]+)',text,re.I)
    if declaration and declaration.group(1).lower() not in ('utf-8','utf8','us-ascii'):raise ValueError('feed must use UTF-8 XML')
    root=ET.fromstring(text); candidates=[]
    if root.tag == '{http://www.w3.org/2005/Atom}feed':
        entries = root.findall('{http://www.w3.org/2005/Atom}entry')
    elif root.tag == 'rss':
        channel = root.find('channel')
        if channel is None: raise ValueError('RSS feed is missing channel')
        entries = channel.findall('item')
    elif root.tag == '{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF':
        entries = root.findall('{http://purl.org/rss/1.0/}item')
    else:
        raise ValueError('response is not a supported RSS/Atom feed')
    if source.get('max_entries') is not None and len(entries) > source['max_entries']:
        raise ValueError('provider result exceeds requested limit')
    for item in entries:
        fields={};link=None
        for child in item:
            key=child.tag.split('}')[-1]
            if key=='link' and child.attrib.get('rel','alternate')=='alternate':link=child.attrib.get('href') or child.text
            fields.setdefault(key,child.text or '')
        published=parse_date(fields.get('pubDate') or fields.get('published') or fields.get('date'))
        updated=parse_date(fields.get('updated'))
        freshness=published or updated
        if not freshness or freshness>now or freshness<now-timedelta(days=days):continue
        if source.get('arxiv_https_links') and isinstance(link,str) and link.startswith('http://arxiv.org/abs/'):
            link = 'https://' + link[len('http://'):]
        try:canonical=safe_url(link,source['allowed_hosts'])
        except (ValueError,UnicodeError):continue
        title=strip_markup(fields.get('title'))
        if not title:continue
        candidates.append({'source_id':source['id'],'source':source['name'],'category':source['category'],'title':title,'source_url':canonical,'published_at':published.isoformat() if published else None,'updated_at':updated.isoformat() if updated else None,'date_basis':'source_published' if published else 'source_updated_not_publication','fetched_at':now.isoformat(),'source_excerpt':strip_markup(fields.get('description') or fields.get('summary') or fields.get('content')),'reviewed':False,'popularity_score':None})
    return candidates


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect refused; review source configuration')


class Fetcher:
    def __init__(self):
        self.last_arxiv = None

    def __call__(self, url):
        host = urlsplit(url).hostname
        if host.endswith('arxiv.org') and self.last_arxiv is not None:
            time.sleep(max(0, 3 - (time.monotonic() - self.last_arxiv)))
        if host.endswith('arxiv.org'):
            self.last_arxiv = time.monotonic()
        request = Request(url, headers={'User-Agent': 'AI-Learning-Notes-Newsletter/1.1 (public metadata reader)'})
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            return response.read(MAX_BYTES+1)


def collect(config, now=None, fetch=None, topic=None):
    now = now or datetime.now(timezone.utc)
    topic = validate_topic() if topic is None else validate_topic(topic)
    is_topic = bool(topic['keywords'])
    days = topic['lookback_days'] if is_topic else config['ranking']['window_days']
    fetch = fetch or Fetcher()
    all_items, failures, queries, warnings = {}, [], [], []
    plans = []
    if is_topic:
        plans, warnings = search_plan(topic, config.get('search', {}), now)
    def retain(item, provenance):
        match = match_topic(item['title'], item['source_excerpt'], topic)
        if not match['eligible']:
            return
        item['provenance'] = [provenance]
        item['matched_keywords'] = match['matched_keywords']
        item['matched_terms'] = match['matched_terms']
        key = dedup_key(item['source_url']) if is_topic else item['source_url']
        if key in all_items:
            prior = all_items[key]
            if provenance not in prior['provenance']:
                prior['provenance'].append(provenance)
            return
        all_items[key] = item
    for source in config['sources']:
        try:
            url = safe_url(source['feed_url'], source['allowed_hosts'])
            content = fetch(url)
            provenance = {'provider': 'rss', 'source_id': source['id'], 'query': '',
                          'request_url': url, 'retrieved_at': now.isoformat()}
            for item in parse_feed(content, source, now, days):
                retain(item, provenance)
        except Exception as error:
            failures.append({'source_id': source['id'], 'error': type(error).__name__, 'message': str(error)[:160]})
    for plan in plans:
        record = {k:plan[k] for k in ('provider','query','request_url','limit')}
        record['retrieved_at'] = now.isoformat()
        try:
            content = fetch(plan['request_url'])
            if plan['provider'] == 'gdelt':
                items, received = parse_gdelt(content, plan, now, days, strip_markup, MAX_BYTES)
            else:
                # arXiv returns HTTP abstract identifiers even on its HTTPS API.
                # Upgrade only the documented arxiv.org abstract-link prefix.
                if len(content) > MAX_BYTES:
                    raise ValueError('oversized XML')
                text = content.decode('utf-8-sig')
                if 'http://arxiv.org/api/errors' in text or 'https://arxiv.org/api/errors' in text:
                    raise ValueError('arXiv returned an API error feed')
                source = {'id': 'arxiv-search', 'name': 'arXiv', 'category': 'papers', 'allowed_hosts': ['arxiv.org'], 'max_entries': plan['limit'], 'arxiv_https_links': True}
                items = parse_feed(text.encode('utf-8'), source, now, days)
                root = ET.fromstring(text)
                if root.tag != '{http://www.w3.org/2005/Atom}feed':
                    raise ValueError('arXiv response is not an Atom feed')
                received = len(root.findall('{http://www.w3.org/2005/Atom}entry'))
                for item in items:
                    if item['published_at']: item['date_basis'] = 'first_arxiv_submission'
                total = root.find('{http://a9.com/-/spec/opensearch/1.1/}totalResults')
                if total is not None and int(total.text or 0) > plan['limit']:
                    record['more_results_available'] = True
            record.update(status='ok', received=received)
            if received >= plan['limit'] or record.get('more_results_available'):
                warnings.append({'provider': plan['provider'], 'code': 'result_limit',
                                 'message': 'Bounded search result limit reached; this is not exhaustive coverage.'})
            for item in items:
                retain(item, {k:record[k] for k in ('provider','query','request_url','retrieved_at')})
        except Exception as error:
            record.update(status='failed', error=type(error).__name__, message=str(error)[:160])
            failures.append({'source_id': plan['provider'], 'error': type(error).__name__, 'message': str(error)[:160]})
        queries.append(record)
    items = sorted(all_items.values(), key=lambda x:(x.get('published_at') or x.get('provider_seen_at') or x.get('updated_at') or '', x['source_url']), reverse=True)
    if is_topic:
        # Exact normalized-title dedup removes obvious cross-provider syndication.
        titles, unique = set(), []
        for item in items:
            key = normalized(item['title'])
            if key not in titles:
                titles.add(key); unique.append(item)
        items = unique
    search_status = ('not_requested' if not is_topic else
                     'failed' if not any(q['status']=='ok' for q in queries) else
                     'partial' if failures or warnings else 'completed')
    return {'schema_version': 1, 'generated_at': now.isoformat(),
            'status': 'partial' if failures or warnings else 'collected',
            'mode': 'topic' if is_topic else 'general', 'topic': topic,
            'ranking': {**config['ranking'], 'window_days': days}, 'review_required': True,
            'candidates': items, 'failures': failures, 'search_status': search_status,
            'searches': queries, 'coverage_warnings': warnings,
            'coverage_note': 'Bounded configured sources only. GDELT matches original titles; arXiv/feed matching also uses excerpts. Not a full-web or popularity ranking.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sources', type=Path, default=ROOT/'daily/data/sources.json')
    parser.add_argument('--topic-config', type=Path, default=ROOT/'daily/data/topics.json')
    parser.add_argument('--keyword', action='append', help='Repeat to replace configured keyword list')
    parser.add_argument('--alias', action='append', default=[], metavar='KEYWORD=ENGLISH')
    parser.add_argument('--exclude', action='append')
    parser.add_argument('--match', choices=('any','all'))
    parser.add_argument('--lookback-days', type=int)
    parser.add_argument('--general', action='store_true', help='Ignore topic config and use general AI feeds')
    args = parser.parse_args()
    try:
        config = json.loads(args.sources.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        topic = validate_topic() if args.general else load_topic(args.topic_config)
        if args.general and any((args.keyword,args.alias,args.exclude,args.match,args.lookback_days)):
            raise ValueError('--general cannot be combined with topic overrides')
        if args.keyword is not None:
            topic['keywords'] = args.keyword
            topic['english_aliases'] = {k:v for k,v in topic['english_aliases'].items() if k in args.keyword}
        for value in args.alias:
            if '=' not in value:
                raise ValueError('--alias requires KEYWORD=ENGLISH')
            key, alias = value.split('=',1)
            topic['english_aliases'].setdefault(key,[]).append(alias)
        for key, value in [('exclude_keywords',args.exclude),('match',args.match),('lookback_days',args.lookback_days)]:
            if value is not None: topic[key] = value
        result = collect(config, topic=validate_topic(topic))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('COLLECTION BLOCKED: '+str(error), file=sys.stderr); return 2
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Collected {len(result['candidates'])} candidates; {len(result['failures'])} source failures; search={result['search_status']}. Editorial review required; nothing published.")
    if result['mode']=='topic' and result['search_status']!='completed': return 2
    return 0 if result['candidates'] else 1


if __name__=='__main__':sys.exit(main())
