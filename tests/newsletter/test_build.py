import copy
from datetime import datetime, timezone, date
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import unquote, urlsplit
from html.parser import HTMLParser
from html import escape as escape_for_test
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/newsletter'))
from edition import validate_edition, load_edition, summary_policy_for, summary_errors, summary_content_digest
from build import outputs, render_issue
from collect import collect, parse_feed


class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.ids=[];self.local_links=[]
    def handle_starttag(self,tag,attrs):
        data=dict(attrs)
        if 'data-local-link' in data:self.local_links.append(data['href'])
        if 'id' in data:self.ids.append(data['id'])
        for key in ('href','src'):
            if data.get(key):self.links.append(data[key])


class NewsletterBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.issue=load_edition(ROOT/'daily/data/issues/2026-10-04.json')
        cls.config=json.loads((ROOT/'daily/config.json').read_text())
        cls.generated=outputs()

    def test_valid_production_contract(self):self.assertEqual(validate_edition(self.issue),[])

    def test_reviewed_short_summary_exceptions_are_bound_and_match_shared_cases(self):
        fixture=json.loads((ROOT/'tests/newsletter/fixtures/summary-exceptions.json').read_text())
        self.assertEqual(summary_content_digest(fixture['base_item'],fixture['date']),fixture['expected_digest'])
        for case in fixture['cases']:
            item=copy.deepcopy(fixture['base_item']);day=case.get('date',fixture['date'])
            for path,value in case['set'].items():
                keys=path.split('.');target=item
                for key in keys[:-1]:target=target[key]
                target[keys[-1]]=value
            if case.get('rebind'):item['summary_length_exception']['content_sha256']=summary_content_digest(item,day)
            with self.subTest(case=case['name']):
                self.assertEqual(not summary_errors(item,day,date.fromisoformat(fixture['today'])),case['valid'])

    def test_supporting_source_urls_are_checked_even_before_length_policies(self):
        issue=copy.deepcopy(self.issue)
        for value in [['javascript:alert(1)'],None,[{}]]:
            issue['items'][0]['summary_sources']=value
            self.assertTrue(any('summary_sources' in e for e in validate_edition(issue)))
        issue['items'][0]['summary_sources']=['https://source.test/verified']
        self.assertEqual(validate_edition(issue),[])
        issue['items'][0]['summary_length_exception']={'reviewed':True}
        self.assertTrue(any('exceptions are unavailable' in e for e in validate_edition(issue)))

    def test_source_only_correction_is_complete_in_pages_search_and_feeds(self):
        issue=load_edition(ROOT/'daily/data/issues/2026-10-07.json')
        self.assertEqual(validate_edition(issue),[])
        self.assertEqual(sum('summary_length_exception' in i for i in issue['items']),5)
        rows=json.loads(self.generated['daily/data/search-index.json'])['records']
        for item in issue['items']:
            row=next(r for r in rows if r['storyId']==item['id'])
            self.assertEqual(row['summarySources'],item['summary_sources'])
            for locale in ('zh-TW','en'):
                self.assertEqual(row['localized'][locale],item[locale])
                page='daily/2026-10-07/'+('en/' if locale=='en' else '')+'index.html'
                html=self.generated[page]
                self.assertIn(escape_for_test(item[locale]['summary']),html)
                for url in item['summary_sources']:self.assertIn(escape_for_test(url),html)
                for format_name in ('feed','atom'):
                    xml=self.generated['daily/'+format_name+('-en' if locale=='en' else '')+'.xml']
                    root=ET.fromstring(xml)
                    text=''.join(root.itertext())
                    self.assertIn(item[locale]['summary'],text)
                    for url in item['summary_sources']:self.assertIn(url,text)
            self.assertNotIn('編輯觀點',item['zh-TW']['summary'])
            self.assertNotIn('Editorial interpretation',item['en']['summary'])

    def test_new_summary_policy_preserves_archive_and_rejects_short_or_padded_text(self):
        self.assertEqual(validate_edition(self.issue),[])
        issue=copy.deepcopy(self.issue);issue.update(date='2026-10-06',reviewed_on='2026-10-06')
        self.assertTrue(any('180–240' in e for e in validate_edition(issue)))
        for item in issue['items']:item['zh-TW']['summary']='測'*200
        self.assertEqual(validate_edition(issue),[])
        for length in (179,241):
            issue['items'][0]['zh-TW']['summary']='測'*length
            self.assertTrue(any('180–240' in e for e in validate_edition(issue)))
        for length in (180,240):
            issue['items'][0]['zh-TW']['summary']='測'*length
            self.assertEqual(validate_edition(issue),[])
        issue['items'][0]['zh-TW']['summary']='測'*179+' \n\t\u0085\u3000'*8
        self.assertTrue(any('180–240' in e for e in validate_edition(issue)))
        issue['items'][0]['zh-TW']['summary']='測'*179+'𠮷'
        self.assertEqual(validate_edition(issue),[])
        html=render_issue(issue,[issue],self.config,'daily/index.html','zh-TW')
        self.assertIn(issue['items'][0]['zh-TW']['summary'],html)
        issue['items'][0]['zh-TW']=None
        self.assertTrue(validate_edition(issue))

    def test_approximately_ten_not_forced_padding(self):
        issue=copy.deepcopy(self.issue);issue['items']=issue['items'][:8]
        self.assertEqual(validate_edition(issue),[])
        issue['items']=issue['items'][:2];self.assertTrue(validate_edition(issue))

    def test_dated_500_policy_shared_fixtures_and_untruncated_output(self):
        cases=json.loads((ROOT/'tests/newsletter/fixtures/summary-policies.json').read_text())
        for case in cases:
            issue=copy.deepcopy(self.issue)
            issue.update(date=case['date'],reviewed_on=case['date'])
            for item in issue['items']:
                item['zh-TW']['summary']='測'*case['characters']+case['tail']
            with self.subTest(case=case):
                self.assertEqual(not validate_edition(issue),case['valid'])
        self.assertIsNone(summary_policy_for('2026-10-04'))
        self.assertEqual(summary_policy_for('2026-10-06')['target_characters'],200)
        self.assertEqual(summary_policy_for('2026-10-07')['target_characters'],500)
        issue=copy.deepcopy(self.issue);issue.update(date='2026-10-07',reviewed_on='2026-10-07')
        for item in issue['items']:item['zh-TW']['summary']='測'*500
        # This synthetic policy fixture has no commissioned image set; keep its render legacy.
        config={k:v for k,v in self.config.items() if k!='enhanced_ui'}
        html=render_issue(issue,[issue],config,'daily/index.html','zh-TW')
        self.assertIn('測'*500,html)
        self.assertEqual(validate_edition(issue),[])

    def test_reject_unreviewed_synthetic_and_future(self):
        for field,value in [('reviewed',False),('synthetic',True),('date','2099-01-01'),('date','2026-02-30'),('schema_version',True)]:
            issue=copy.deepcopy(self.issue);issue[field]=value;self.assertTrue(validate_edition(issue),field)

    def test_reject_missing_translation_duplicate_and_unsafe_url(self):
        mutations=[lambda i:i['items'][0]['en'].pop('caveat'),lambda i:i['items'][1].update(id=i['items'][0]['id']),lambda i:i['items'][1].update(source_url=i['items'][0]['source_url']),lambda i:i['items'][0].update(source_url='javascript:alert(1)'),lambda i:i['items'][0].update(published_date='2099-01-01')]
        for change in mutations:
            issue=copy.deepcopy(self.issue);change(issue);self.assertTrue(validate_edition(issue))

    def test_escape_all_editorial_html(self):
        issue=copy.deepcopy(self.issue);attack='</span><script>alert("x")</script>'
        issue['items'][0]['en']['title']=attack
        html=render_issue(issue,[issue],self.config,'daily/index.html','en')
        self.assertNotIn(attack,html);self.assertIn('&lt;script&gt;',html)

    def test_deterministic_outputs(self):self.assertEqual(self.generated,outputs())

    def test_generated_outputs_current(self):
        for name,html in self.generated.items():self.assertEqual((ROOT/name).read_text(),html,name)

    def test_two_locales_real_archive_only(self):
        self.assertIn('daily/en/index.html',self.generated)
        self.assertIn('daily/archive/en/index.html',self.generated)
        self.assertNotIn('2026-09-30/index.html',''.join(self.generated))
        self.assertIn('lang="en"',self.generated['daily/en/index.html'])
        latest=load_edition(max((ROOT/'daily/data/issues').glob('*.json')))
        self.assertEqual(self.generated['daily/index.html'].count('data-card'),len(latest['items']))
        self.assertEqual(self.generated['daily/2026-10-04/index.html'].count('data-card'),10)

    def test_english_static_routes_preserve_locale(self):
        for name,html in self.generated.items():
            if not name.endswith('/en/index.html'):continue
            parser=Links();parser.feed(html)
            for link in parser.local_links:
                if link.startswith('#') or urlsplit(link).scheme or not link.endswith('index.html'):continue
                target=((ROOT/name).parent/link).resolve()
                if target==ROOT/'index.html':continue
                self.assertEqual(target.parent.name,'en',(name,link))

    def test_no_bogus_email_form_or_secrets(self):
        html=self.generated['daily/index.html']
        self.assertNotIn('type="email"',html);self.assertNotIn('id="subscription"',html)
        self.assertIn('不收集信箱',html)
        for content in self.generated.values():self.assertNotIn('api-key',content)

    def test_xml_feeds_separate_and_well_formed(self):
        for path,xml in self.generated.items():
            if path.endswith('.xml'):
                root=ET.fromstring(xml);self.assertIn('/daily/2026-10-04/',xml)
                self.assertNotIn('harness_engineering_article',xml)
                self.assertIn(root.tag,('rss','{http://www.w3.org/2005/Atom}feed'))

    def test_legacy_feed_explicitly_excludes_daily(self):
        spec=importlib.util.spec_from_file_location('legacy_feed',ROOT/'scripts/build-feed.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertIsNone(module.url_to_local_path(module.SITE+'/daily/index.html'))
        self.assertIsNone(module.url_to_local_path(module.SITE+'/daily/2026-10-04/index.html'))
        self.assertIsNotNone(module.url_to_local_path(module.SITE+'/harness_engineering_article_public.html'))

    def test_internal_links_and_duplicate_ids(self):
        for name,html in self.generated.items():
            if not name.endswith('.html'):continue
            parser=Links();parser.feed(html);self.assertEqual(len(parser.ids),len(set(parser.ids)),name)
            for link in parser.links:
                url=urlsplit(link)
                if url.scheme or url.netloc:continue
                if not url.path:
                    if url.fragment:self.assertIn(url.fragment,parser.ids,(name,link))
                    continue
                target=(ROOT/name).parent/unquote(url.path)
                if target.is_dir():target=target/'index.html'
                self.assertTrue(target.exists(),(name,link))

    def test_all_three_layouts_generated_by_date(self):
        themes=set()
        for day in range(1,4):
            issue=copy.deepcopy(self.issue);issue['date']=f'2026-10-0{day}'
            html=render_issue(issue,[issue],self.config,'daily/index.html','zh-TW')
            for theme in self.config['themes']:
                if f'<body class="{theme}"' in html:themes.add(theme)
        self.assertEqual(themes,set(self.config['themes']))


class CollectorTests(unittest.TestCase):
    source={'id':'test','name':'Primary source','category':'news','feed_url':'https://source.test/feed','allowed_hosts':['source.test']}
    now=datetime(2026,10,4,15,tzinfo=timezone.utc)
    xml=b'<rss><channel><item><title>&lt;b&gt;A story&lt;/b&gt;</title><link>https://source.test/a</link><pubDate>Sat, 03 Oct 2026 10:00:00 +0000</pubDate><description>&lt;script&gt;untrusted text&lt;/script&gt;</description></item></channel></rss>'
    def test_feed_parsing_and_recency(self):
        items=parse_feed(self.xml,self.source,self.now);self.assertEqual(len(items),1);self.assertEqual(items[0]['title'],'A story');self.assertFalse(items[0]['reviewed']);self.assertIsNone(items[0]['popularity_score'])
        self.assertEqual(parse_feed(self.xml,self.source,datetime(2026,11,1,tzinfo=timezone.utc)),[])
    def test_entities_and_oversize_rejected(self):
        for data in (b'<!DOCTYPE rss [<!ENTITY x "boom">]><rss/>',b'x'*2_000_001,'<!DOCTYPE rss [<!ENTITY x "boom">]><rss/>'.encode('utf-16'),'<rss/>'.encode('utf-16-le')):
            with self.assertRaises(ValueError):parse_feed(data,self.source,self.now)
    def test_foreign_url_rejected(self):self.assertEqual(parse_feed(self.xml.replace(b'https://source.test/a',b'https://foreign.test/a'),self.source,self.now),[])
    def test_failures_are_visible_not_fake_news(self):
        config={'sources':[self.source],'ranking':{'window_days':7}}
        def fail(url):raise TimeoutError('timed out')
        report=collect(config,self.now,fail);self.assertEqual(report['candidates'],[]);self.assertEqual(report['status'],'partial');self.assertEqual(len(report['failures']),1)
    def test_atom_and_deduplication(self):
        config={'sources':[self.source,self.source],'ranking':{'window_days':7}}
        report=collect(config,self.now,lambda url:self.xml);self.assertEqual(len(report['candidates']),1)
        atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom</title><link href="https://source.test/atom"/><published>2026-10-03T10:00:00Z</published></entry></feed>'
        self.assertEqual(len(parse_feed(atom,self.source,self.now)),1)


class BrowserFixtureCallbackTests(unittest.TestCase):
    """Only exercise route callback arguments; no browser or image rendering."""
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('newsletter_browser_fixtures',ROOT/'tests/newsletter/browser_check.py')
        cls.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.module)
    class Route:
        def __init__(self):self.calls=[]
        def fulfill(self,**kwargs):self.calls.append(('fulfill',kwargs))
        def abort(self):self.calls.append(('abort',None))
    def test_image_handlers_have_one_argument_and_capture_their_own_filename(self):
        names=['wide.svg','portrait.svg','large-dimensions.svg','broken.jpg']
        handlers=[self.module.image_fixture_handler(name) for name in names]
        for name,handler in zip(names,handlers):
            self.assertEqual(list(inspect.signature(handler).parameters),['route'])
            route=self.Route();handler(route)
            self.assertEqual(route.calls,[('fulfill',{'path':str(ROOT/'tests/newsletter/fixtures/images'/name),'content_type':'image/svg+xml' if name.endswith('.svg') else 'image/jpeg'})])
    def test_failure_handlers_capture_each_case_without_a_request_default_parameter(self):
        invalid={'records':[{'sourceUrl':'javascript:alert(1)'}]}
        cases=['abort','malformed','oversized','unsafe-index']
        handlers=[self.module.archive_failure_handler(case,invalid) for case in cases]
        for case,handler in zip(cases,handlers):
            self.assertEqual(list(inspect.signature(handler).parameters),['route'])
            route=self.Route();handler(route)
            if case=='abort':self.assertEqual(route.calls,[('abort',None)]);continue
            action,body=route.calls[0];self.assertEqual(action,'fulfill');self.assertEqual(body['status'],200)
            if case=='malformed':self.assertEqual(body['body'],'{broken')
            if case=='oversized':self.assertEqual(len(body['body']),4000001)
            if case=='unsafe-index':self.assertEqual(json.loads(body['body']),invalid)


if __name__=='__main__':unittest.main()
