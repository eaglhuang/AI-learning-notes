import copy
from datetime import datetime, timezone, date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/newsletter'))
from topics import validate_topic, match_topic, safe_url, normalized, parse_timestamp
from discovery import search_plan, parse_gdelt, dedup_key
from collect import collect, strip_markup, parse_feed
from create_draft import create_draft
from edition import validate_edition
from build import render_issue, topic_label

NOW = datetime(2026,10,4,15,tzinfo=timezone.utc)
TOPIC = {'schema_version':1,'keywords':['AI'],'english_aliases':{},'match':'any','exclude_keywords':[],'lookback_days':7}
CONFIG = {'sources':[],'ranking':{'window_days':7,'target_items':10},
          'search':{'providers':['gdelt'],'max_results':100,'allowed_article_hosts':['source.test']}}

def articles(count=7):
    return json.dumps({'articles':[{'title':f'AI story {i}','url':f'https://source.test/{i}',
                                  'seendate':'20261003T120000Z'} for i in range(count)]}).encode()

def report(count=7):
    return collect(CONFIG,NOW,lambda url:articles(count),TOPIC)

def reviewed_topic_issue():
    result=create_draft(report(),'2026-10-04')
    result.update(reviewed=True,reviewed_on='2026-10-04')
    for field in ('title','coverage','editorial_note'):
        result[field]={'zh-TW':'測試專題','en':'Test topic'}
    for item in result['items']:
        item.update(published_date='2026-10-03',date_verification_required=False)
        for locale in ('zh-TW','en'):
            item[locale]={k:'Test original editorial content' for k in ('title','summary','takeaway','caveat')}
    return result

class TopicTests(unittest.TestCase):
    def test_cross_runtime_matching_fixtures(self):
        for case in json.loads((ROOT/'tests/newsletter/fixtures/topic-matches.json').read_text()):
            config={k:v for k,v in case.items() if k in TOPIC}
            result=match_topic(case['title'],case['excerpt'],validate_topic(config))
            self.assertEqual(result['eligible'],case['eligible'],case['name'])
            self.assertEqual(result['matched_terms'],case['matched_terms'],case['name'])
    def test_invalid_settings_fail_before_query(self):
        bad=[{'schema_version':True},{'match':'xor'},{'lookback_days':True},{'lookback_days':31},
             {'keywords':['']},{'keywords':['AI" OR domain:evil.test']},{'keywords':['ＡＩ＂']},
             {'keywords':['AI\nrobot']},{'keywords':['x'*81]},{'keywords':['AI']*9},
             {'keywords':['AI'],'english_aliases':{'other':['AI']}},{'english_aliases':[]},
             {'keywords':['AI'],'english_aliases':{'AI':['中文']}},{'toString':'bad'},
             {'keywords':['AI'],'english_aliases':{'AI':['robot'],'ａｉ':['test']}},
             {'exclude_keywords':['AI']}]
        for config in bad:
            with self.assertRaises(ValueError,msg=str(config)): validate_topic(config)
    def test_empty_default_and_duplicate_normalization(self):
        self.assertEqual(validate_topic()['keywords'],[])
        self.assertEqual(validate_topic({'keywords':['ＡＩ','ai']})['keywords'],['AI'])
    def test_request_uses_keywords_aliases_and_source_constraint(self):
        topic=validate_topic({'keywords':['具身智能'],'english_aliases':{'具身智能':['embodied AI']}})
        plans,warnings=search_plan(topic,CONFIG['search'],NOW)
        self.assertEqual(warnings,[])
        query=parse_qs(urlsplit(plans[0]['request_url']).query)['query'][0]
        self.assertIn('"embodied AI"',query);self.assertIn('domainis:source.test',query)
        self.assertNotIn('具身智能',query)
        self.assertEqual(parse_qs(urlsplit(plans[0]['request_url']).query)['startdatetime'],['20260927150000'])
    def test_chinese_only_reports_unsupported_coverage(self):
        result=collect(CONFIG,NOW,lambda url:self.fail('unsupported query should not be sent'),{'keywords':['具身智能']})
        self.assertEqual(result['search_status'],'failed')
        self.assertEqual(result['coverage_warnings'][0]['code'],'needs_english_alias')
        self.assertEqual(result['candidates'],[])
    def test_general_mode_does_not_query_search_providers(self):
        result=collect(CONFIG,NOW,lambda url:self.fail('empty topic must not trigger search'))
        self.assertEqual(result['mode'],'general');self.assertEqual(result['search_status'],'not_requested')
    def test_real_search_discovery_without_feed_candidates(self):
        seen=[]
        result=collect(CONFIG,NOW,lambda url:(seen.append(url) or articles()),TOPIC)
        self.assertEqual(len(result['candidates']),7);self.assertEqual(len(seen),1)
        self.assertTrue(seen[0].startswith('https://api.gdeltproject.org/'))
        self.assertEqual(result['search_status'],'completed')
        item=result['candidates'][0]
        self.assertIsNone(item['published_at']);self.assertIsNotNone(item['provider_seen_at'])
        self.assertEqual(item['matched_terms'],['AI']);self.assertEqual(item['provenance'][0]['query'],result['searches'][0]['query'])
    def test_no_general_filler_with_keywords(self):
        self.assertEqual(collect(CONFIG,NOW,lambda url:articles(),{'keywords':['quantum']})['candidates'],[])
    def test_malformed_timeout_and_oversize_are_failures(self):
        for payload in (b'{}',b'<html>error</html>',b'{"articles":"not an array"}',b'x'*2_000_001):
            result=collect(CONFIG,NOW,lambda url:payload,TOPIC)
            self.assertEqual(result['search_status'],'failed');self.assertEqual(len(result['failures']),1)
        def fail(url):raise TimeoutError('timeout')
        self.assertEqual(collect(CONFIG,NOW,fail,TOPIC)['searches'][0]['status'],'failed')
    def test_successful_empty_is_distinct_from_failure(self):
        result=collect(CONFIG,NOW,lambda url:b'{"articles":[]}',TOPIC)
        self.assertEqual(result['search_status'],'completed');self.assertEqual(result['failures'],[])
    def test_limit_is_visible(self):
        config=copy.deepcopy(CONFIG);config['search']['max_results']=10
        result=collect(config,NOW,lambda url:articles(10),TOPIC)
        self.assertEqual(result['search_status'],'partial');self.assertEqual(result['coverage_warnings'][0]['code'],'result_limit')
        with self.assertRaises(ValueError):create_draft(result,'2026-10-04')
        self.assertEqual(len(create_draft(result,'2026-10-04',True)['items']),10)
    def test_old_future_unsafe_hosts_ports_and_scripts(self):
        data=json.loads(articles());data['articles'][0]['seendate']='20260801T000000Z'
        data['articles'][1]['seendate']='20261201T000000Z';data['articles'][2]['url']='https://evil.test/x'
        data['articles'][3]['url']='https://source.test:8443/x';data['articles'][4]['url']='javascript:alert(1)'
        data['articles'][5]['title']='<script>AI title</script>'
        result=collect(CONFIG,NOW,lambda url:json.dumps(data).encode(),TOPIC)
        self.assertEqual(len(result['candidates']),2);self.assertNotIn('<script>',str(result['candidates']))
    def test_tracking_and_title_dedup_preserve_real_query(self):
        self.assertEqual(dedup_key('https://source.test/a?utm_source=x&id=7#part'),'https://source.test/a?id=7')
        self.assertNotEqual(dedup_key('https://source.test/a?id=7'),dedup_key('https://source.test/a?id=8'))
        data=json.loads(articles());data['articles'][1]['url']=data['articles'][0]['url']+'?utm_source=x'
        data['articles'][3]['title']=data['articles'][2]['title']
        self.assertEqual(len(collect(CONFIG,NOW,lambda url:json.dumps(data).encode(),TOPIC)['candidates']),5)
    def test_arxiv_query_and_error_feed(self):
        config=copy.deepcopy(CONFIG);config['search']['providers']=['arxiv']
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>AI paper</title><link href="http://arxiv.org/abs/2610.00001v1"/><published>2026-10-03T10:00:00Z</published><summary>AI advances</summary></entry></feed>'
        result=collect(config,NOW,lambda url:xml,TOPIC)
        self.assertEqual(len(result['candidates']),1);self.assertIn('submittedDate',result['searches'][0]['query'])
        self.assertEqual(result['candidates'][0]['source_url'],'https://arxiv.org/abs/2610.00001v1')
        bad=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad</id></entry></feed>'
        self.assertEqual(collect(config,NOW,lambda url:bad,TOPIC)['search_status'],'failed')
    def test_draft_refuses_fewer_than_six(self):
        for count in (0,1,5):
            with self.assertRaises(ValueError):create_draft(report(count),'2026-10-04')
    def test_draft_preserves_evidence_and_cannot_publish(self):
        draft=create_draft(report(),'2026-10-04')
        self.assertFalse(draft['reviewed']);self.assertEqual(draft['items'][0]['published_date'],'')
        self.assertEqual(draft['items'][0]['topic_evidence']['matched_terms'],['AI'])
        self.assertTrue(validate_edition(draft))
    def test_reviewed_topic_and_bilingual_escaped_label(self):
        issue=reviewed_topic_issue();self.assertEqual(validate_edition(issue),[])
        config=json.loads((ROOT/'daily/config.json').read_text())
        for locale, label in [('en','Topic edition: AI'),('zh-TW','關鍵字專題：AI')]:
            html=render_issue(issue,[issue],config,'daily/index.html',locale)
            self.assertIn(label,html);self.assertIn('topic-settings-form',html)
        self.assertEqual(topic_label({},'en'),'General AI edition')
    def test_forged_matches_unrelated_partial_dates_rejected(self):
        mutations=[lambda x:x['items'][0]['topic_evidence'].update(matched_terms=['robot']),
                   lambda x:x['items'][0]['topic_evidence'].update(source_title='Nothing relevant'),
                   lambda x:x['items'][0].update(published_date='2026-09-01'),
                   lambda x:x['items'][0].update(date_verification_required=True),
                   lambda x:x['discovery'].update(search_status='partial'),
                   lambda x:x['discovery'].update(searches=[]),
                   lambda x:x['items'][0]['topic_evidence']['provenance'][0].update(request_url='https://api.gdeltproject.org:8443/x')]
        for change in mutations:
            issue=reviewed_topic_issue();change(issue);self.assertTrue(validate_edition(issue))
    def test_python_and_email_validation_parity(self):
        valid=reviewed_topic_issue();bad=copy.deepcopy(valid);bad['items'][0]['topic_evidence']['matched_terms']=[]
        draft=create_draft(report(),'2026-10-04');partial=copy.deepcopy(valid);partial['discovery']['search_status']='partial'
        cases=[valid,bad,draft,partial]
        command="import {validateEmailEdition} from './scripts/newsletter/email-service.mjs';let s='';for await(const c of process.stdin)s+=c;console.log(JSON.stringify(JSON.parse(s).map(x=>validateEmailEdition(x).length===0)));"
        result=subprocess.run(['node','--input-type=module','-e',command],input=json.dumps(cases),text=True,capture_output=True,cwd=ROOT,check=True)
        self.assertEqual(json.loads(result.stdout),[not validate_edition(x) for x in cases])
    def test_invalid_feed_root_is_visible_failure(self):
        config=copy.deepcopy(CONFIG);config['sources']=[{'id':'rss','name':'RSS','category':'news','feed_url':'https://source.test/rss','allowed_hosts':['source.test']}]
        result=collect(config,NOW,lambda url:b'<html><body>Temporarily unavailable</body></html>' if url.endswith('/rss') else b'{"articles":[]}',TOPIC)
        self.assertEqual(result['status'],'partial');self.assertEqual(result['search_status'],'partial');self.assertEqual(len(result['failures']),1)
    def test_updated_only_feed_requires_publication_verification(self):
        xml=('<feed xmlns="http://www.w3.org/2005/Atom">'+''.join(f'<entry><title>AI update {i}</title><link href="https://source.test/{i}"/><updated>2026-10-03T10:00:00Z</updated></entry>' for i in range(6))+'</feed>').encode()
        config=copy.deepcopy(CONFIG);config['sources']=[{'id':'rss','name':'RSS','category':'news','feed_url':'https://source.test/rss','allowed_hosts':['source.test']}]
        result=collect(config,NOW,lambda url:xml if url.endswith('/rss') else b'{"articles":[]}',TOPIC)
        self.assertEqual(len(result['candidates']),6)
        self.assertIsNone(result['candidates'][0]['published_at']);self.assertEqual(result['candidates'][0]['date_basis'],'source_updated_not_publication')
        draft=create_draft(result,'2026-10-04')
        self.assertTrue(all(x['date_verification_required'] and x['published_date']=='' for x in draft['items']))
    def test_arxiv_single_quote_urls_and_result_cap(self):
        config=copy.deepcopy(CONFIG);config['search']['providers']=['arxiv'];config['search']['max_results']=10
        def xml(count):return ('<feed xmlns="http://www.w3.org/2005/Atom">'+''.join(f"<entry><title>AI paper {i}</title><link href='http://arxiv.org/abs/2610.{i:05}'/><published>2026-10-03T10:00:00Z</published></entry>" for i in range(count))+'</feed>').encode()
        self.assertEqual(len(collect(config,NOW,lambda url:xml(1),TOPIC)['candidates']),1)
        self.assertEqual(collect(config,NOW,lambda url:xml(11),TOPIC)['search_status'],'failed')
    def test_timestamp_calendar_and_offset_parity(self):
        cases=['2026-10-03T12:00:00Z','2026-10-03T12:00:00.123456+08:00','2026-02-30T12:00:00Z','2026-10-03T12:00:00+0000','2026-10-03T12:00:00+00:60','0000-01-01T12:00:00Z']
        expected=[True,True,False,False,False,False]
        actual=[]
        for stamp in cases:
            try:parse_timestamp(stamp);actual.append(True)
            except ValueError:actual.append(False)
        self.assertEqual(actual,expected)
        for stamp,valid in zip(cases,expected):
            issue=reviewed_topic_issue();issue['discovery']['collected_at']=stamp
            self.assertEqual(not validate_edition(issue),valid)
        command="import {validTimestamp} from './daily/topic-config.mjs';let s='';for await(const c of process.stdin)s+=c;console.log(JSON.stringify(JSON.parse(s).map(validTimestamp)));"
        result=subprocess.run(['node','--input-type=module','-e',command],input=json.dumps(cases),text=True,capture_output=True,cwd=ROOT,check=True)
        self.assertEqual(json.loads(result.stdout),expected)
    def test_cli_draft_failure_does_not_write_or_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'report.json';out=Path(tmp)/'draft.json';source.write_text(json.dumps(report(5)))
            result=subprocess.run([sys.executable,str(ROOT/'scripts/newsletter/create_draft.py'),str(source),'--date','2026-10-04','--output',str(out)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(out.exists())
            out.write_text('preserve');source.write_text(json.dumps(report()))
            result=subprocess.run([sys.executable,str(ROOT/'scripts/newsletter/create_draft.py'),str(source),'--date','2026-10-04','--output',str(out)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertEqual(out.read_text(),'preserve')

if __name__=='__main__':unittest.main()
