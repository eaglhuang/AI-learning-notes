"""Versioned topic configuration and literal evidence matching (no translation)."""
import json
import re
import unicodedata
from pathlib import Path
from validate_issue import _unique_object, _url_key
from urllib.parse import urlsplit, parse_qs
from datetime import datetime

DEFAULT_TOPIC = {'schema_version': 1, 'keywords': [], 'english_aliases': {},
                 'match': 'any', 'exclude_keywords': [], 'lookback_days': 7}
TOPIC_FIELDS = set(DEFAULT_TOPIC)
PROVIDER_HOSTS = {'gdelt': {'api.gdeltproject.org'}, 'arxiv': {'export.arxiv.org'}}


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def term(value):
    if not isinstance(value, str) or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('keywords must be visible strings without control characters')
    value = ' '.join(unicodedata.normalize('NFKC', value).split())
    if not 1 <= len(value) <= 80 or any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('keywords must contain 1–80 visible characters')
    if any(c in value for c in '"\\:()[]{}<>'):
        raise ValueError('keywords are literal text; quotes, query operators and markup are not allowed')
    return value


def terms(values):
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError('use an array of at most 8 keywords')
    result = []
    for value in values:
        value = term(value)
        if normalized(value) not in [normalized(x) for x in result]:
            result.append(value)
    return result


_MISSING = object()


def validate_topic(value=_MISSING):
    if value is _MISSING:
        value = {}
    if not isinstance(value, dict) or set(value) - TOPIC_FIELDS:
        raise ValueError('topic must be an object with known version-1 fields')
    result = {**DEFAULT_TOPIC, **value}
    if type(result['schema_version']) is not int or result['schema_version'] != 1:
        raise ValueError('topic.schema_version must be integer 1')
    result['keywords'] = terms(result['keywords'])
    result['exclude_keywords'] = terms(result['exclude_keywords'])
    if result['match'] not in ('any', 'all'):
        raise ValueError('topic.match must be any (OR) or all (AND)')
    if type(result['lookback_days']) is not int or not 1 <= result['lookback_days'] <= 30:
        raise ValueError('topic.lookback_days must be an integer from 1 to 30')
    aliases = result['english_aliases']
    if not isinstance(aliases, dict):
        raise ValueError('topic.english_aliases must map a keyword to English alternatives')
    known = {normalized(k): k for k in result['keywords']}
    clean = {}
    for keyword, values in aliases.items():
        key = normalized(term(keyword))
        if key not in known or known[key] in clean:
            raise ValueError('alias keys must uniquely name a configured keyword')
        values = terms(values)
        if len(values) > 3 or any(not x.isascii() or not re.search('[A-Za-z]', x) for x in values):
            raise ValueError('each keyword accepts at most 3 explicit English aliases')
        clean[known[key]] = values
    result['english_aliases'] = clean
    if not result['keywords'] and (clean or result['exclude_keywords']):
        raise ValueError('exclusions and aliases require at least one keyword')
    return result


def load_topic(path):
    return validate_topic(json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_object))


def groups(topic):
    return [(key, [key] + topic['english_aliases'].get(key, [])) for key in topic['keywords']]


def contains(text, keyword):
    text, keyword = normalized(text), normalized(keyword)
    # Latin token boundaries avoid AI matching "said". CJK uses literal substrings.
    left = r'(?<![a-z0-9_])' if re.match('[a-z0-9_]', keyword) else ''
    right = r'(?![a-z0-9_])' if re.search('[a-z0-9_]$', keyword) else ''
    return re.search(left + re.escape(keyword) + right, text) is not None


def match_topic(title, excerpt, topic):
    # Do not join fields: a phrase must occur inside one actual source field.
    fields = (title, excerpt)
    matched_terms, matched_keywords = [], []
    for key, alternatives in groups(topic):
        found = [x for x in alternatives if any(contains(text, x) for text in fields)]
        if found:
            matched_keywords.append(key)
            matched_terms.extend(found)
    excluded = [x for x in topic['exclude_keywords'] if any(contains(text, x) for text in fields)]
    relevant = (not topic['keywords'] or bool(matched_keywords))
    if topic['match'] == 'all':
        relevant = len(matched_keywords) == len(topic['keywords'])
    return {'eligible': relevant and not excluded, 'matched_keywords': matched_keywords,
            'matched_terms': list(dict.fromkeys(matched_terms)), 'excluded_terms': excluded}


def safe_url(value, allowed_hosts=None):
    url = _url_key(value)
    parsed = urlsplit(url)
    if parsed.port not in (None, 443):
        raise ValueError('only standard HTTPS ports are allowed')
    if allowed_hosts is not None and parsed.hostname not in allowed_hosts:
        raise ValueError('source host is not allowlisted')
    return url


def parse_timestamp(value):
    if not isinstance(value,str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",value):
        raise ValueError('timestamp must be canonical ISO seconds with timezone')
    if value[-1] != 'Z' and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError('timestamp timezone offset is invalid')
    return datetime.fromisoformat(value.replace('Z','+00:00'))


def validate_provenance(record):
    if not isinstance(record, dict) or record.get('provider') not in ('rss', 'gdelt', 'arxiv'):
        raise ValueError('unsupported provider')
    url = safe_url(record.get('request_url'), PROVIDER_HOSTS.get(record['provider']))
    query = record.get('query')
    if not isinstance(query, str) or len(query) > 4000:
        raise ValueError('query must be retained')
    parsed = urlsplit(url)
    if record['provider'] in ('gdelt','arxiv'):
        field, path = ('query','/api/v2/doc/doc') if record['provider']=='gdelt' else ('search_query','/api/query')
        if not query or parsed.path != path or parse_qs(parsed.query).get(field) != [query]:
            raise ValueError('query must match the exact provider request')
    elif query:
        raise ValueError('RSS collection has no search query')
    retrieved = record.get('retrieved_at')
    if not isinstance(retrieved,str):
        raise ValueError('retrieval timestamp required')
    parse_timestamp(retrieved)


def validate_topic_evidence(item, topic):
    evidence = item.get('topic_evidence')
    if not isinstance(evidence, dict):
        return ['topic_evidence is required for keyword picks']
    title, excerpt = evidence.get('source_title'), evidence.get('source_excerpt')
    if not isinstance(title, str) or not title.strip() or len(title) > 1800 or not isinstance(excerpt, str) or len(excerpt) > 1800:
        return ['topic_evidence must retain bounded source title and excerpt']
    result = match_topic(title, excerpt, topic)
    errors = []
    if not result['eligible']:
        errors.append('source evidence does not meet topic keywords/exclusions')
    for key in ('matched_keywords', 'matched_terms'):
        if evidence.get(key) != result[key]:
            errors.append('topic_evidence.' + key + ' does not match source evidence')
    provenance = evidence.get('provenance')
    if not isinstance(provenance, list) or not 1 <= len(provenance) <= 16:
        errors.append('topic_evidence.provenance must retain 1–16 discovery records')
    else:
        for record in provenance:
            try:
                validate_provenance(record)
            except (ValueError, TypeError, UnicodeError):
                errors.append('topic provenance requires safe provider URL, query and retrieval timestamp')
    return errors
