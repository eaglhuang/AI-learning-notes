#!/usr/bin/env python3
"""Validate source readiness and exact collection windows without network I/O."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from edition import CONTRACT
from topics import parse_timestamp, safe_url
from validate_issue import _unique_object

ROOT = Path(__file__).resolve().parents[2]
TAIPEI = ZoneInfo('Asia/Taipei')
SOURCE_FIELDS = {'id', 'name', 'category', 'feed_url', 'enabled', 'allowed_hosts',
                 'feed_hosts', 'article_hosts', 'metadata'}
METADATA_FIELDS = {'source_family', 'region', 'language', 'attribution',
                   'full_translation_eligibility', 'documentation_urls', 'license_evidence_urls'}
RIGHTS = {'unknown_requires_item_review', 'permission_required',
          'conditional_author_permission', 'conditional_per_item_license'}


def utc_time(value):
    """Never infer UTC for an undated or timezone-free observation."""
    try:
        stamp = parse_timestamp(value) if isinstance(value, str) else value
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('timezone-aware timestamp required')
        return stamp.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError('valid timezone-aware timestamp required') from error


def window_bounds(collected_at, days):
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('collection window must be 1–30 whole days')
    end = utc_time(collected_at)
    try:
        return end - timedelta(days=days), end
    except OverflowError as error:
        raise ValueError('collection window is outside supported dates') from error


def taipei_date(value):
    try:
        return utc_time(value).astimezone(TAIPEI).date().isoformat()
    except OverflowError as error:
        raise ValueError('timestamp is outside supported Taipei dates') from error


def hosts(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 40 or len(set(map(str, values))) != len(values):
        raise ValueError('source host list must contain 1–40 unique DNS hosts')
    for host in values:
        if (not isinstance(host, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host)
                or '..' in host or urlsplit(safe_url('https://' + host)).netloc != host):
            raise ValueError('source hosts must be exact lowercase DNS names')
    return list(values)


def source_metadata(value):
    if not isinstance(value, dict) or set(value) - METADATA_FIELDS:
        raise ValueError('unknown source metadata fields')
    result = deepcopy(value)
    for key, item in result.items():
        if key.endswith('_urls'):
            if not isinstance(item, list) or len(item) > 8:
                raise ValueError('source documentation must be a bounded URL list')
            for url in item:
                safe_url(url)
        elif not isinstance(item, str) or not item.strip() or len(item) > 400 or re.search(r'[\x00-\x1f\x7f]', item):
            raise ValueError('source metadata must contain bounded plain text')
    if result.get('full_translation_eligibility', 'unknown_requires_item_review') not in RIGHTS:
        raise ValueError('source-level metadata cannot grant blanket full-translation rights')
    return result


def validate_source_config(value):
    if not isinstance(value, dict) or set(value) - {'schema_version', 'sources', 'ranking', 'search'}:
        raise ValueError('invalid source configuration fields')
    if 'schema_version' in value and (type(value['schema_version']) is not int or value['schema_version'] != 2):
        raise ValueError('source configuration schema_version must be 2')
    sources = value.get('sources')
    if not isinstance(sources, list) or len(sources) > 40:
        raise ValueError('sources must be a bounded array')
    result = deepcopy(value)
    result['schema_version'] = 2
    result['sources'] = []
    ids = set()
    for source in sources:
        if not isinstance(source, dict) or set(source) - SOURCE_FIELDS:
            raise ValueError('invalid source fields')
        identifier = source.get('id')
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', identifier) or identifier in ids:
            raise ValueError('source IDs must be unique safe slugs')
        ids.add(identifier)
        if not isinstance(source.get('name'), str) or not source['name'].strip() or len(source['name']) > 160:
            raise ValueError('source name is required and bounded')
        if source.get('category') not in CONTRACT['categories']:
            raise ValueError('unsupported source category')
        enabled = source.get('enabled', True)
        if type(enabled) is not bool:
            raise ValueError('source enabled must be a boolean')
        if 'allowed_hosts' in source and ('feed_hosts' in source or 'article_hosts' in source):
            raise ValueError('do not mix legacy and separate source host lists')
        legacy = source.get('allowed_hosts')
        feed_hosts = hosts(source.get('feed_hosts', legacy))
        article_hosts = hosts(source.get('article_hosts', legacy))
        safe_url(source.get('feed_url'), feed_hosts)
        normalized = {k: deepcopy(v) for k, v in source.items() if k != 'allowed_hosts'}
        normalized.update(enabled=enabled, feed_hosts=feed_hosts, article_hosts=article_hosts,
                          metadata=source_metadata(source.get('metadata', {})))
        result['sources'].append(normalized)
    ranking = value.get('ranking')
    if not isinstance(ranking, dict) or set(ranking) - {'window_days', 'target_items', 'method', 'popularity_metrics_available'}:
        raise ValueError('invalid ranking configuration')
    days = ranking.get('window_days', 2)
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('ranking window_days must be 1–30')
    target = ranking.get('target_items', 10)
    if type(target) is not int or not CONTRACT['min_items'] <= target <= CONTRACT['max_items']:
        raise ValueError('ranking target_items is outside the edition contract')
    if ranking.get('popularity_metrics_available', False) is not False:
        raise ValueError('this collector has no measured popularity ranking')
    result['ranking'] = dict(ranking, window_days=days, target_items=target)
    settings = value.get('search', {})
    if not isinstance(settings, dict) or set(settings) - {'providers', 'max_results', 'allowed_article_hosts'}:
        raise ValueError('invalid public search settings')
    result['search'] = deepcopy(settings)
    return result


def read_config(path):
    return validate_source_config(json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=_unique_object))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, default=ROOT/'daily/data/sources.json')
    parser.add_argument('--catalog', type=Path, default=ROOT/'daily/data/source-catalog.json')
    parser.add_argument('--check', action='store_true', required=True)
    args = parser.parse_args()
    try:
        config = read_config(args.sources)
        catalog = json.loads(args.catalog.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        channels = catalog['channels']
        if not isinstance(channels, list) or len(channels) > 40 or len({x['id'] for x in channels}) != len(channels):
            raise ValueError('invalid discovery catalog')
        for channel in channels:
            safe_url(channel['discovery_url'])
            if channel['automatic_fetch_enabled'] is not False:
                raise ValueError('discovery catalog cannot activate a collector')
        print(json.dumps({'status': 'configuration_validated_without_network',
                          'enabled_feeds': sum(s['enabled'] for s in config['sources']),
                          'disabled_feeds': sum(not s['enabled'] for s in config['sources']),
                          'general_window_hours': config['ranking']['window_days'] * 24,
                          'discovery_only_channels': len(channels)}))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as error:
        print('SOURCE CONFIG BLOCKED: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
