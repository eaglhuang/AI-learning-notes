"""Source readiness uses synthetic feeds only; no network or publication."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/newsletter'))
from source_config import validate_source_config, utc_time, window_bounds, taipei_date
from collect import collect, parse_feed
from create_draft import create_draft
from pipeline import check_report, reviewed_errors, prepare
from edition import validate_edition, edition_today, load_edition
from writer import check_draft
from topics import validate_topic

FIXTURE = json.loads((ROOT/'tests/newsletter/fixtures/source-readiness.json').read_text())
NOW = utc_time(FIXTURE['now'])
SOURCE = {'id':'fixture','name':'Fixture engineering publication','category':'writing',
          'feed_url':'https://feed.test/rss','feed_hosts':['feed.test'],
          'article_hosts':['article.test'],'enabled':True,
          'metadata':{'source_family':'practitioner_author','region':'test',
                      'full_translation_eligibility':'unknown_requires_item_review'}}
CONFIG = {'sources':[SOURCE],'ranking':{'window_days':2,'target_items':10}}


def feed(count=7, stamp='2026-10-06T12:00:00Z', query=''):
    return ('<rss><channel>'+''.join(
        f'<item><title>Offline AI story {i}</title><link>https://article.test/{i}{query}</link>'
        f'<pubDate>{stamp}</pubDate><description>Offline fixture details.</description></item>'
        for i in range(count))+'</channel></rss>').encode()


def report(config=None, content=None):
    return collect(config or CONFIG, NOW, lambda url: content if content is not None else feed())


class SourceReadinessTests(unittest.TestCase):
    def test_disabled_source_has_no_io_or_fabricated_receipt(self):
        config=deepcopy(CONFIG);config['sources'][0]['enabled']=False
        result=collect(config,NOW,lambda url:self.fail('disabled feed must never be fetched'))
        self.assertEqual(result['disabled_sources'],['fixture'])
        self.assertEqual(result['feed_receipts'],[])
        self.assertEqual(result['failures'],[])
        self.assertEqual(result['candidates'],[])

    def test_invalid_enablement_and_duplicate_identity_fail_before_io(self):
        for value in ['false',0,None,{}]:
            config=deepcopy(CONFIG);config['sources'][0]['enabled']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                collect(config,NOW,lambda url:self.fail('invalid configuration must fail before I/O'))
        config=deepcopy(CONFIG);config['sources'].append(deepcopy(SOURCE))
        with self.assertRaises(ValueError):validate_source_config(config)

    def test_config_normalization_preserves_legacy_hosts_and_is_idempotent(self):
        legacy=deepcopy(CONFIG);s=legacy['sources'][0]
        s.pop('feed_hosts');s.pop('article_hosts');s['allowed_hosts']=['feed.test','article.test']
        normalized=validate_source_config(legacy)
        self.assertEqual(normalized,validate_source_config(normalized))
        self.assertEqual(normalized['sources'][0]['article_hosts'],['feed.test','article.test'])
        self.assertIn('allowed_hosts',legacy['sources'][0])

    def test_exact_timestamp_boundaries_match_collection_and_draft(self):
        for case in FIXTURE['timestamp_cases']:
            with self.subTest(case=case['name']):
                parsed=parse_feed(feed(stamp=case['stamp']),SOURCE,NOW,2)
                self.assertEqual(bool(parsed),case['eligible'])
                raw=report()
                for candidate in raw['candidates']:candidate['published_at']=case['stamp']
                if case['eligible']:
                    self.assertEqual(len(create_draft(raw,'2026-10-07')['items']),7)
                else:
                    with self.assertRaises(ValueError):create_draft(raw,'2026-10-07')

    def test_collection_clock_requires_timezone_and_bounds(self):
        for value in [datetime(2026,10,7), '2026-10-07T00:00:00', '0001-01-01T00:00:00+23:59']:
            with self.assertRaises(ValueError):utc_time(value)
        with self.assertRaises(ValueError):window_bounds(NOW,True)
        start,end=window_bounds(NOW,2);self.assertEqual((end-start).total_seconds(),172800)

    def test_feed_and_article_hosts_are_independent(self):
        fetched=[]
        result=collect(CONFIG,NOW,lambda url:(fetched.append(url),FIXTURE['rss'].encode())[1])
        self.assertEqual(fetched,['https://feed.test/rss'])
        self.assertEqual(result['candidates'][0]['source_url'],'https://article.test/story')
        wrong=FIXTURE['rss'].replace('https://article.test/story','https://feed.test/unapproved')
        self.assertEqual(report(content=wrong.encode())['candidates'],[])

    def test_three_feed_formats_keep_byline_unverified_and_source_context(self):
        for format_name in ['rss','atom','rdf']:
            with self.subTest(format=format_name):
                item=parse_feed(FIXTURE[format_name].encode(),SOURCE,NOW,2)[0]
                self.assertEqual(item['byline'],'Guest Engineer')
                self.assertTrue(item['byline_verification_required'])
                self.assertEqual(item['content_kind'],'unclassified_feed_entry')
                self.assertEqual(item['source_context'],SOURCE['metadata'])
                self.assertEqual(item['source'],'Fixture engineering publication')

    def test_updated_only_never_becomes_a_publication_timestamp(self):
        text=('<feed xmlns="http://www.w3.org/2005/Atom">'+''.join(
            f'<entry><title>Offline {i}</title><link href="https://article.test/{i}"/>'
            '<updated>2026-10-06T12:00:00Z</updated></entry>' for i in range(7))+'</feed>').encode()
        result=report(content=text);draft=create_draft(result,'2026-10-07')
        self.assertTrue(all(i['date_verification_required'] and i['published_at']=='' and i['published_date']=='' for i in draft['items']))
        self.assertEqual(result['candidates'][0]['date_basis'],'source_updated_not_publication')

    def test_general_tracking_dedup_retains_distinct_source_provenance(self):
        config=deepcopy(CONFIG);config['sources'].append({**deepcopy(SOURCE),'id':'other-feed','feed_url':'https://feed.test/other'})
        def fetch(url):return feed(count=1,query='?id=2&amp;utm_source='+('a' if url.endswith('rss') else 'b'))
        result=collect(config,NOW,fetch)
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(len(result['candidates'][0]['provenance']),2)
        text=feed(count=1,query='?id=2').replace(b'</channel>',feed(count=1,query='?id=3').split(b'<channel>')[1].split(b'</channel>')[0]+b'</channel>')
        self.assertEqual(len(report(content=text)['candidates']),2)

    def test_html_and_timeout_are_partial_not_successful_empty_results(self):
        for fetch in [lambda url:FIXTURE['invalid_html'].encode(),lambda url:(_ for _ in ()).throw(TimeoutError('offline timeout'))]:
            result=collect(CONFIG,NOW,fetch)
            self.assertEqual(result['status'],'partial');self.assertEqual(result['feed_receipts'][0]['status'],'failed')
            with self.assertRaises(ValueError):create_draft(result,'2026-10-07')

    def test_import_cannot_use_disabled_source_or_upgrade_rights(self):
        good=report();topic=good['topic'];check_report(good,topic,'2026-10-07',CONFIG)
        disabled=deepcopy(CONFIG);disabled['sources'][0]['enabled']=False
        altered=deepcopy(good);altered['disabled_sources']=['fixture'];altered['feed_receipts']=[]
        with self.assertRaises(ValueError):check_report(altered,topic,'2026-10-07',disabled)
        for where in ['candidate','receipt']:
            altered=deepcopy(good)
            target=altered['candidates'][0] if where=='candidate' else altered['candidates'][0]['provenance'][0]
            target['source_context']['full_translation_eligibility']='conditional_author_permission'
            with self.subTest(where=where),self.assertRaises(ValueError):check_report(altered,topic,'2026-10-07',CONFIG)

    def test_import_cannot_round_away_staleness_or_conceal_feed_failures(self):
        result=report();topic=result['topic']
        result['candidates'][0]['published_at']='2026-10-04T23:59:59Z'
        with self.assertRaises(ValueError):check_report(result,topic,'2026-10-07',CONFIG)
        result=report();result['feed_receipts'][0]['status']='failed'
        with self.assertRaises(ValueError):check_report(result,topic,'2026-10-07',CONFIG)
        result=report();result.pop('feed_receipts')
        with self.assertRaises(ValueError):check_report(result,topic,'2026-10-07',CONFIG)
        result=report();result['feed_receipts'][0]['eligible_candidates']=0
        with self.assertRaises(ValueError):check_report(result,topic,'2026-10-07',CONFIG)
        result=report();result['feed_receipts'][0]={'source_id':'fixture','status':'failed'}
        result['failures']=[{'source_id':'fixture','error':'TimeoutError'}];result['status']='partial'
        with self.assertRaises(ValueError):check_report(result,topic,'2026-10-07',CONFIG)

    def test_taipei_edition_date_does_not_follow_utc_midnight(self):
        clock=utc_time('2026-10-06T16:30:00Z')
        result=collect(CONFIG,clock,lambda url:feed(stamp='2026-10-06T12:00:00Z'))
        self.assertEqual(taipei_date(clock),'2026-10-07')
        check_report(result,result['topic'],'2026-10-07',CONFIG)
        self.assertEqual(create_draft(result,'2026-10-07')['date'],'2026-10-07')
        with self.assertRaises(ValueError):create_draft(result,'2026-10-06')

    def test_future_same_day_report_is_blocked_against_trusted_clock(self):
        trusted=utc_time('2026-10-05T01:00:00Z')
        future=collect(CONFIG,utc_time('2026-10-05T02:00:00Z'),lambda url:feed(stamp='2026-10-05T01:30:00Z'))
        with self.assertRaisesRegex(ValueError,'trusted run clock'):
            check_report(future,future['topic'],'2026-10-05',CONFIG,now=trusted)
        with self.assertRaisesRegex(ValueError,'trusted run clock'):
            create_draft(future,'2026-10-05',now=trusted)
        with tempfile.TemporaryDirectory() as folder:
            run=Path(folder)/'run'
            state=prepare(run,config=CONFIG,topic=future['topic'],issue_date='2026-10-05',candidate_report=future,now=trusted)
            self.assertEqual(state['state'],'blocked_collection')
            self.assertFalse((run/'draft.json').exists())
        # Equality is allowed, and an older same-day report is not silently recollected.
        check_report(future,future['topic'],'2026-10-05',CONFIG,now=utc_time('2026-10-05T02:00:00Z'))
        check_report(future,future['topic'],'2026-10-05',CONFIG,now=utc_time('2026-10-05T03:00:00Z'))
        # Both prepare checks honor its injected clock, not a second wall-clock read.
        simulated=utc_time('2099-01-01T01:00:00Z')
        simulated_report=collect(CONFIG,simulated,lambda url:feed(stamp='2099-01-01T00:30:00Z'))
        with tempfile.TemporaryDirectory() as folder:
            state=prepare(Path(folder)/'simulation',config=CONFIG,topic=simulated_report['topic'],
                          issue_date='2099-01-01',candidate_report=simulated_report,now=simulated)
            self.assertEqual(state['state'],'awaiting_editorial_review')

    def test_taipei_clock_is_shared_by_publication_review_and_offline_writer(self):
        for case in FIXTURE['calendar_cases']:
            with self.subTest(case=case),patch('edition.datetime') as clock:
                clock.now.return_value=utc_time(case['instant'])
                self.assertEqual(edition_today().isoformat(),case['date'])
        now=utc_time('2026-10-04T16:30:00Z')
        result=collect(CONFIG,now,lambda url:feed(stamp='2026-10-04T15:00:00Z'))
        selection=create_draft(result,'2026-10-05')
        issue=deepcopy(selection);issue.update(reviewed=True,reviewed_on='2026-10-05')
        for field in ['title','coverage','editorial_note']:
            issue[field]={'zh-TW':'僅限離線測試','en':'Offline fixture only'}
        for item in issue['items']:
            item['date_verification_required']=False
            for locale in ['zh-TW','en']:
                item[locale]={field:'Offline fixture only' for field in ['title','summary','takeaway','caveat']}
        with patch('edition.datetime') as clock:
            clock.now.return_value=now
            check_draft(selection)
            self.assertEqual(validate_edition(issue),[])
            self.assertEqual(reviewed_errors(issue,selection),[])
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'2026-10-05.json';path.write_text(json.dumps(issue))
                self.assertEqual(load_edition(path),issue)
            future=deepcopy(issue);future['date']='2026-10-06'
            self.assertTrue(any('future' in error for error in validate_edition(future)))
        current=json.loads((ROOT/'daily/data/issues/2026-10-07.json').read_text())
        with patch('edition.datetime') as clock:
            clock.now.return_value=utc_time('2026-10-06T16:00:00Z')
            self.assertEqual(validate_edition(current),[])  # Includes reviewed short-summary dates.

    def test_history_url_and_explicit_event_dedup_do_not_fill_a_quota(self):
        result=report();result['candidates'][1]['event_id']='project:v1:2026-10-06'
        history=[{'reviewed':True,'items':[{'id':'old-url','source_url':'https://article.test/0?utm_source=archive'},
                   {'id':'old-event','source_url':'https://article.test/different','event_id':'project:v1:2026-10-06'}]}]
        with self.assertRaisesRegex(ValueError,'only 5'):create_draft(result,'2026-10-07',published_issues=history)
        draft=create_draft(result,'2026-10-07')
        self.assertFalse(draft['reviewed']);self.assertTrue(validate_edition(draft))
        one=[{'reviewed':True,'items':history[0]['items'][:1]}]
        draft=create_draft(result,'2026-10-07',published_issues=one)
        self.assertEqual(len(draft['items']),6);self.assertEqual(len(draft['selection_diagnostics']['excluded_published']),1)

    def test_preview_requires_verified_exact_publication_time(self):
        selection=create_draft(report(),'2026-10-07');issue=deepcopy(selection)
        issue['items'][0]['published_at']='2026-10-04T23:59:59Z'
        issue['items'][0]['published_date']='2026-10-04'
        self.assertTrue(any('exact collection window' in e for e in reviewed_errors(issue,selection)))
        issue=deepcopy(selection);issue['items'][0].pop('published_at')
        self.assertTrue(any('timezone-aware publication timestamp' in e for e in reviewed_errors(issue,selection)))
        issue=deepcopy(selection);issue['items'][0]['published_at']='2026-10-06T20:00:00+08:00'
        self.assertFalse(any('instant changed' in e for e in reviewed_errors(issue,selection)))

    def test_shipped_sources_are_48_hours_with_four_unactivated_additions(self):
        config=validate_source_config(json.loads((ROOT/'daily/data/sources.json').read_text()))
        self.assertEqual(config['ranking']['window_days'],2)
        self.assertEqual(sum(s['enabled'] for s in config['sources']),4)
        self.assertEqual({s['id'] for s in config['sources'] if not s['enabled']},{'arxiv-lg','arxiv-cl','cna-tech','martin-fowler'})
        self.assertEqual(json.loads((ROOT/'daily/data/topics.json').read_text())['lookback_days'],2)
        catalog=json.loads((ROOT/'daily/data/source-catalog.json').read_text())
        self.assertTrue(all(c['automatic_fetch_enabled'] is False for c in catalog['channels']))
        self.assertTrue({'google-news-tw','google-news-en','martin-fowler','simon-willison'}<=set(catalog['priority_channels']))


if __name__ == '__main__':unittest.main()
