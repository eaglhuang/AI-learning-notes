import copy
from datetime import datetime, timezone, date
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import unquote, urlsplit
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/newsletter'))
from edition import validate_edition, load_edition
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

    def test_approximately_ten_not_forced_padding(self):
        issue=copy.deepcopy(self.issue);issue['items']=issue['items'][:8]
        self.assertEqual(validate_edition(issue),[])
        issue['items']=issue['items'][:2];self.assertTrue(validate_edition(issue))

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
        self.assertEqual(self.generated['daily/index.html'].count('data-card'),10)

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


if __name__=='__main__':unittest.main()
