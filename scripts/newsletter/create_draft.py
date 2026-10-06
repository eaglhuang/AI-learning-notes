#!/usr/bin/env python3
"""Select collected newsletter candidates into a never-published editorial draft."""
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from edition import CONTRACT
from topics import validate_topic, match_topic, safe_url
from discovery import dedup_key
from validate_issue import _unique_object


def create_draft(report, issue_date, allow_partial=False):
    issue_date = date.fromisoformat(issue_date)
    if issue_date > date.today():
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
        if report.get('failures') and not allow_partial:
            raise ValueError('feed collection is partial; inspect failures before using --allow-partial')
    days = topic['lookback_days'] if is_topic else report.get('ranking',{}).get('window_days',7)
    if type(days) is not int or not 1 <= days <= 30:
        raise ValueError('collection window must be 1–30 days')
    selected, seen = [], set()
    for candidate in report.get('candidates', []):
        result = match_topic(candidate['title'], candidate['source_excerpt'], topic)
        if not result['eligible']:
            continue
        url = safe_url(candidate['source_url'])
        key = dedup_key(url)
        if key in seen:
            continue
        seen.add(key)
        published = candidate.get('published_at')
        stamp = published or candidate.get('provider_seen_at') or candidate.get('updated_at')
        try:
            day = datetime.fromisoformat(stamp.replace('Z','+00:00')).date()
        except (ValueError, AttributeError):
            continue
        if not issue_date-timedelta(days=days) <= day <= issue_date:
            continue
        selected.append({'id': 'pick-'+hashlib.sha256(key.encode()).hexdigest()[:12],
                         'source_url': url, 'source': candidate['source'], 'category': candidate['category'],
                         'published_date': day.isoformat() if published else '',
                         'date_verification_required': not bool(published),
                         ('topic_evidence' if is_topic else 'source_evidence'): {'source_title': candidate['title'], 'source_excerpt': candidate['source_excerpt'],
                                            'matched_keywords': result['matched_keywords'], 'matched_terms': result['matched_terms'],
                                            'provenance': candidate.get('provenance', []),
                                            'provider_seen_at': candidate.get('provider_seen_at'),
                                            'source_updated_at': candidate.get('updated_at'),
                                            'date_basis': candidate.get('date_basis')},
                         **{locale: {field: '' for field in CONTRACT['item_text_limits']} for locale in CONTRACT['locales']}})
        if len(selected) >= CONTRACT.get('target_items',10):
            break
    if len(selected) < CONTRACT['min_items']:
        raise ValueError(f"only {len(selected)} relevant recent unique candidates; need at least {CONTRACT['min_items']}. No filler draft created; narrow/adjust the explicit settings or skip this edition")
    return {'schema_version': 2, 'date': issue_date.isoformat(), 'synthetic': False,
            'reviewed': False, 'reviewed_on': '', 'topic': topic, 'collection_window_days': days,
            'discovery': {'collected_at': report['generated_at'], 'search_status': status,
                          'limitations_acknowledged': False, 'searches': report['searches'],
                          'failures': report.get('failures', []), 'coverage_warnings': report.get('coverage_warnings', []),
                          'coverage_note': report.get('coverage_note','')},
            **{field: {locale: '' for locale in CONTRACT['locales']} for field in CONTRACT['issue_text_fields']},
            'items': selected}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidates', type=Path)
    parser.add_argument('--date', default=date.today().isoformat())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    try:
        report = json.loads(args.candidates.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)
        draft = create_draft(report, args.date, args.allow_partial)
        issue_dir = Path(__file__).resolve().parents[2]/'daily/data/issues'
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
