"""Bounded, no-key public search adapters. Returned metadata is untrusted evidence."""
from datetime import datetime, timezone, timedelta
import json
import re
from urllib.parse import urlencode, urlsplit, parse_qsl, urlunsplit
from topics import groups, safe_url, normalized
from validate_issue import _unique_object

ENDPOINTS = {'gdelt': 'https://api.gdeltproject.org/api/v2/doc/doc',
             'arxiv': 'https://export.arxiv.org/api/query'}
TRACKING = {'fbclid', 'gclid', 'mc_cid', 'mc_eid'}


def dedup_key(url):
    parsed = urlsplit(safe_url(url))
    query = [(k,v) for k,v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.casefold().startswith('utm_') and k.casefold() not in TRACKING]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))


def search_plan(topic, settings, now):
    providers = settings.get('providers', ['gdelt', 'arxiv'])
    if not isinstance(providers, list) or not providers or len(set(providers)) != len(providers) or any(p not in ENDPOINTS for p in providers):
        raise ValueError('search.providers must select gdelt and/or arxiv without duplicates')
    hosts = settings.get('allowed_article_hosts')
    if not isinstance(hosts, list) or not 1 <= len(hosts) <= 40:
        raise ValueError('search.allowed_article_hosts must contain 1–40 exact DNS hosts')
    for host in hosts:
        if not isinstance(host, str) or urlsplit(safe_url('https://' + host)).netloc != host or ':' in host:
            raise ValueError('search article allowlist must contain exact lowercase DNS hosts')
    limit = settings.get('max_results', 100)
    if type(limit) is not int or not 10 <= limit <= 250:
        raise ValueError('search.max_results must be 10–250')
    start = now - timedelta(days=topic['lookback_days'])
    plans, warnings = [], []
    for provider in providers:
        alternatives = []
        missing = []
        for key, choices in groups(topic):
            supported = [x for x in choices if provider != 'gdelt' or x.isascii()]
            if not supported:
                missing.append(key)
            alternatives.extend(supported)
        alternatives = list(dict.fromkeys(alternatives))
        if missing:
            warnings.append({'provider': provider, 'code': 'needs_english_alias', 'keywords': missing,
                             'message': 'GDELT searches English-translated coverage; add explicit English aliases for these keywords.'})
        if not alternatives:
            continue
        if provider == 'gdelt':
            query = '(' + ' OR '.join('"'+x+'"' for x in alternatives) + ')'
            query += ' (' + ' OR '.join('domainis:'+h for h in hosts) + ')'
            params = {'query': query, 'mode': 'artlist', 'format': 'json', 'maxrecords': limit,
                      'sort': 'datedesc', 'startdatetime': start.strftime('%Y%m%d%H%M%S'),
                      'enddatetime': now.strftime('%Y%m%d%H%M%S')}
        else:
            query = '(' + ' OR '.join('(ti:"'+x+'" OR abs:"'+x+'")' for x in alternatives) + ')'
            query += ' AND submittedDate:['+start.strftime('%Y%m%d%H%M')+' TO '+now.strftime('%Y%m%d%H%M')+']'
            params = {'search_query': query, 'start': 0, 'max_results': limit,
                      'sortBy': 'submittedDate', 'sortOrder': 'descending'}
        if len(query) > 4000:
            raise ValueError('search query exceeds 4000 characters; use fewer or shorter keywords/aliases')
        plans.append({'provider': provider, 'query': query,
                      'request_url': ENDPOINTS[provider]+'?'+urlencode(params), 'limit': limit,
                      'allowed_hosts': hosts if provider == 'gdelt' else ['arxiv.org']})
    return plans, warnings


def parse_gdelt(content, plan, now, days, strip_markup, max_bytes):
    if len(content) > max_bytes:
        raise ValueError('oversized JSON')
    data = json.loads(content.decode('utf-8-sig'), object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or not isinstance(data.get('articles'), list):
        raise ValueError('GDELT response must contain an articles array; not a successful empty result')
    if len(data['articles']) > plan['limit']:
        raise ValueError('GDELT result exceeds requested limit')
    items = []
    for article in data['articles']:
        if not isinstance(article, dict) or not isinstance(article.get('title'), str) or not isinstance(article.get('seendate'), str):
            raise ValueError('malformed GDELT article metadata')
        try:
            url = safe_url(article.get('url'), plan['allowed_hosts'])
            observed = datetime.strptime(article['seendate'], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        except (ValueError, TypeError, UnicodeError):
            continue
        if not now-timedelta(days=days) <= observed <= now:
            continue
        title = strip_markup(article['title'])
        if not title:
            continue
        items.append({'source_id': 'gdelt', 'source': urlsplit(url).hostname, 'category': 'news',
                      'title': title, 'source_url': url, 'published_at': None,
                      'provider_seen_at': observed.isoformat(), 'date_basis': 'provider_seen_not_publication',
                      'fetched_at': now.isoformat(), 'source_excerpt': '', 'reviewed': False,
                      'popularity_score': None})
    return items, len(data['articles'])
