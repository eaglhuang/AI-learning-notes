#!/usr/bin/env python3
"""Select collected newsletter candidates into a never-published editorial draft."""
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from pathlib import Path
import sys
from edition import CONTRACT, load_edition
from topics import validate_topic, match_topic, safe_url, parse_timestamp
from discovery import dedup_key
from validate_issue import _unique_object
from source_config import window_bounds, utc_time, taipei_date


def read_published_history(directory):
    return [load_edition(path) for path in sorted(Path(directory).glob('*.json'))]


def history_keys(issues):
    urls, events = set(), set()
    for issue in issues:
        if not isinstance(issue, dict) or issue.get('reviewed') is not True or not isinstance(issue.get('items'), list):
            raise ValueError('published history must contain reviewed editions')
        for item in issue['items']:
            urls.add(dedup_key(item['source_url']))
            for key in ('id', 'event_id'):
                if isinstance(item.get(key), str) and item[key]: events.add(item[key])
    return urls, events


def create_draft(report, issue_date, allow_partial=False, published_issues=(), *, now=None):
    issue_date = date.fromisoformat(issue_date)
    trusted_now = utc_time(now if now is not None else datetime.now(timezone.utc))
    if issue_date.isoformat() > taipei_date(trusted_now):
        raise ValueError('draft date cannot be in the future')
    topic = validate_topic(report.get('topic'))
    is_topic = bool(topic['keywords'])
    if report.get('mode') != ('topic' if is_topic else 'general'):
        raise ValueError('collection mode and topic settings do not agree')
    status = report.get('search_status')
    if is_topic:
        if status not in ('completed','partial') or not any(q.get('status')=='ok' for q in report.get('searches',[])):
            raise ValueError('no successful keyword search; inspect provider failures or missing English aliases')
        if status != 'completed' and not allow_partial:
            raise ValueError('search is partial; inspect failures/warnings, then explicitly use --allow-partial if appropriate')
    else:
        if status != 'not_requested' or report.get('status') not in ('collected','partial'):
            raise ValueError('general mode requires a valid fixed-feed collection report')
        if report.get('status') == 'partial' and not allow_partial:
            raise ValueError('feed collection is partial; inspect failures and warnings before using --allow-partial')
    days = topic['lookback_days'] if is_topic else report.get('ranking',{}).get('window_days',2)
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('collection window must be 1–30 days')
    cutoff, collected = window_bounds(report.get('generated_at'), days)
    if collected > trusted_now:
        raise ValueError('candidate collection timestamp cannot be later than the trusted run clock')
    if taipei_date(collected) != issue_date.isoformat():
        raise ValueError('draft date must match the collection Taipei calendar date')
    target = report.get('ranking', {}).get('target_items', 10)
    if type(target) is not int or not CONTRACT['min_items'] <= target <= CONTRACT['max_items']:
        raise ValueError('target item count is outside the edition contract')
    published_urls, published_events = history_keys(published_issues)
    selected, seen, events, excluded = [], set(), set(), []
    for candidate in report.get('candidates', []):
        result = match_topic(candidate['title'], candidate['source_excerpt'], topic)
        if not result['eligible']:
            continue
        url = safe_url(candidate['source_url'])
        key = dedup_key(url)
        event = candidate.get('event_id')
        if event is not None and (not isinstance(event, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:/._-]{0,159}',event)):
            raise ValueError('candidate event ID must be a bounded safe identifier')
        if key in published_urls or event and event in published_events:
            excluded.append({'source_url':url,'reason':'already_published_url_or_event'})
            continue
        if key in seen or event and event in events:
            continue
        published = candidate.get('published_at')
        stamp = published or candidate.get('provider_seen_at') or candidate.get('updated_at')
        try:
            observed = utc_time(stamp)
        except (ValueError, TypeError):
            continue
        if not cutoff <= observed <= collected:
            continue
        seen.add(key)
        if event: events.add(event)
        day = parse_timestamp(published).date() if published else None
        selected.append({'id': 'pick-'+hashlib.sha256(key.encode()).hexdigest()[:12],
                         'source_url': url, 'source': candidate['source'], 'category': candidate['category'],
                         'published_at': published or '',
                         'published_date': day.isoformat() if day else '',
                         **({'event_id':event} if event else {}),
                         'date_verification_required': not bool(published),
                         ('topic_evidence' if is_topic else 'source_evidence'): {'source_title': candidate['title'], 'source_excerpt': candidate['source_excerpt'],
                                            'matched_keywords': result['matched_keywords'], 'matched_terms': result['matched_terms'],
                                            'provenance': candidate.get('provenance', []),
                                            'provider_seen_at': candidate.get('provider_seen_at'),
                                            'source_published_at': candidate.get('published_at'),
                                            'source_updated_at': candidate.get('updated_at'),
                                            'date_basis': candidate.get('date_basis'),
                                            'source_context': deepcopy(candidate.get('source_context', {})),
                                            'byline': candidate.get('byline', ''),
                                            'byline_verification_required': True,
                                            'content_kind': candidate.get('content_kind', 'unclassified_discovery_metadata')},
                         **{locale: {field: '' for field in CONTRACT['item_text_limits']} for locale in CONTRACT['locales']}})
        if len(selected) >= target:
            break
    if len(selected) < CONTRACT['min_items']:
        raise ValueError(f"only {len(selected)} relevant recent unique candidates; need at least {CONTRACT['min_items']}. No filler draft created; narrow/adjust the explicit settings or skip this edition")
    return {'schema_version': 2, 'date': issue_date.isoformat(), 'synthetic': False,
            'reviewed': False, 'reviewed_on': '', 'topic': topic, 'collection_window_days': days,
            'collection_window': {'start_at':cutoff.isoformat(),'end_at':collected.isoformat(),
                                  'duration_hours':days*24,'inclusive':True},
            'selection_diagnostics': {'excluded_published':excluded},
            'discovery': {'collected_at': report['generated_at'], 'search_status': status,
                          'limitations_acknowledged': False, 'searches': report['searches'],
                          'failures': report.get('failures', []), 'coverage_warnings': report.get('coverage_warnings', []),
                          'feed_receipts': deepcopy(report.get('feed_receipts', [])),
                          'disabled_sources': list(report.get('disabled_sources', [])),
                          'coverage_note': report.get('coverage_note','')},
            **{field: {locale: '' for locale in CONTRACT['locales']} for field in CONTRACT['issue_text_fields']},
            'items': selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidates', type=Path)
    parser.add_argument('--date', default=taipei_date(datetime.now(timezone.utc)))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    try:
        report = json.loads(args.candidates.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        issue_dir = Path(__file__).resolve().parents[2]/'daily/data/issues'
        draft = create_draft(report, args.date, args.allow_partial, read_published_history(issue_dir))
        if args.output.resolve().is_relative_to(issue_dir):
            raise ValueError('write drafts outside daily/data/issues; only reviewed editions belong there')
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as handle:
            handle.write(json.dumps(draft,ensure_ascii=False,indent=2)+'\n')
    except (ValueError, KeyError, TypeError, OSError) as error:
        print('DRAFT BLOCKED: '+str(error),file=sys.stderr);return 1
    print(f"Drafted {len(draft['items'])} newsletter picks. Write and verify both languages and publication dates before approving. Nothing published or emailed.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
