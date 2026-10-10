import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/newsletter'))
from image_policy import load_images, validate_image, MAX_IMAGE_BYTES
from build import outputs, search_index, script_json, render_issue


class ImageAndUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_real_images_bound_by_story_and_budget(self):
        issue = json.loads((ROOT/'daily/data/issues/2026-10-07.json').read_text())
        images = load_images(ROOT, issue['items'])
        selected = [images[item['id']] for item in issue['items']]
        self.assertEqual(len(selected), 7)
        self.assertEqual(sum(i['bytes'] for i in selected), 1329475)
        source=images[issue['items'][1]['id']]
        self.assertEqual(source['path'], 'daily/assets/stories/simon-datasette-parsable-2048.webp')
        self.assertFalse(source['ai_generated']);self.assertEqual(source['license']['spdx'],'Apache-2.0')
        self.assertEqual(sum(i['ai_generated'] for i in selected),6)
        self.assertTrue((ROOT/'daily/assets/stories/codex-local-tracing.jpg').is_file())

    def test_webp_is_static_and_extension_matches_decoded_format(self):
        path=self.root/'static.webp';Image.new('RGB',(128,81),'red').save(path,format='WEBP')
        self.assertEqual(validate_image(path)['width'],128)
        lossless=self.root/'lossless.webp';Image.new('RGBA',(128,81),(20,40,60,128)).save(lossless,format='WEBP',lossless=True)
        self.assertEqual(validate_image(lossless)['height'],81)
        wrong=self.root/'wrong.jpg';wrong.write_bytes(path.read_bytes())
        with self.assertRaisesRegex(ValueError,'matching extensions'):validate_image(wrong)
        animated=self.root/'animated.webp'
        Image.new('RGB',(20,20),'red').save(animated,format='WEBP',save_all=True,
            append_images=[Image.new('RGB',(20,20),'blue')],duration=100,loop=0)
        with self.assertRaisesRegex(ValueError,'static'):validate_image(animated)

    def test_webp_preflight_rejects_large_animated_and_malformed_headers_before_decoder(self):
        def riff(kind,payload):
            chunk=kind+len(payload).to_bytes(4,'little')+payload+(b'\0'if len(payload)%2 else b'')
            return b'RIFF'+(len(chunk)+4).to_bytes(4,'little')+b'WEBP'+chunk
        vp8=lambda width,height:b'\x10\x00\x00\x9d\x01\x2a'+width.to_bytes(2,'little')+height.to_bytes(2,'little')
        vp8l=lambda width,height:b'\x2f'+((width-1)|((height-1)<<14)).to_bytes(4,'little')
        cases=[riff(b'VP8 ',vp8(4096,4096)),riff(b'VP8L',vp8l(16384,16384)),
               riff(b'VP8X',b'\x02'+b'\0'*9),riff(b'VP8X',b'\0'*10),
               riff(b'ANIM',b'\0'*6),riff(b'ANMF',b'\0'*16),
               riff(b'VP8 ',vp8(0,1)),riff(b'VP8L',b'\x2f\0\0\0\xe0'),
               riff(b'VP8 ',b'short'),riff(b'VP8 ',vp8(8,8))+b'trailing',
               b'RIFF'+(4).to_bytes(4,'little')+b'WEBP']
        for n,raw in enumerate(cases):
            for suffix in ['.webp','.jpg']:
                path=self.root/(str(n)+suffix);path.write_bytes(raw)
                with self.subTest(case=n,suffix=suffix),patch('image_policy.Image.open')as decoder:
                    with self.assertRaises(ValueError):validate_image(path)
                    decoder.assert_not_called()
        # A valid-looking small header still requires full compressed-pixel validation.
        fake=self.root/'header-only.webp';fake.write_bytes(riff(b'VP8 ',vp8(8,8)))
        with self.assertRaises(ValueError):validate_image(fake)

    def test_source_image_requires_bound_license_notice_and_safe_links(self):
        shutil.copytree(ROOT/'daily',self.root/'daily');path=self.root/'daily/data/image-manifest.json'
        baseline=json.loads(path.read_text());issue=json.loads((self.root/'daily/data/issues/2026-10-07.json').read_text())
        index=next(n for n,e in enumerate(baseline['images'])if not e['ai_generated'])
        for change in [lambda e:e.pop('license'),lambda e:e['license'].update(spdx='unknown'),
                       lambda e:e['license'].update(image_url='javascript:alert(1)'),
                       lambda e:e['license'].update(license_path='../private.txt'),
                       lambda e:e['license'].update(notice_sha256='0'*64),
                       lambda e:e['license'].update(image_git_blob_sha='invented'),
                       lambda e:e.update(ai_generated=True),lambda e:e.update(ai_generated=0)]:
            value=copy.deepcopy(baseline);change(value['images'][index]);path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):load_images(self.root,issue['items'])
        path.write_text(json.dumps(baseline));notice=self.root/baseline['images'][index]['license']['notice_path']
        notice.write_text('changed notice')
        with self.assertRaisesRegex(ValueError,'hash'):load_images(self.root,issue['items'])

    def test_source_credit_is_visible_localized_and_linked(self):
        generated=outputs();manifest=json.loads((ROOT/'daily/data/image-manifest.json').read_text())
        source=next(e for e in manifest['images']if not e['ai_generated'])
        # The permanent Oct7 edition must retain its original image and license
        # even after the homepage advances to another reviewed edition.
        for name in ['daily/2026-10-07/index.html','daily/2026-10-07/en/index.html']:
            html=generated[name]
            self.assertEqual(html.count('data-image-kind="licensed-source"'),1)
            self.assert_source_credit(html,source)

    def assert_source_credit(self,html,source):
        for locale in ['zh-TW','en']:
            self.assertIn(source['credit'][locale],html)
        self.assertIn(source['license']['image_url'],html)
        self.assertIn(source['license']['source_url'],html)
        self.assertIn('LICENSE-APACHE-2.0.txt',html)
        self.assertIn('SIMON-IMAGE-NOTICE.txt',html)
        self.assertIn(Path(source['path']).name,html)

    def assert_edition_image_policy(self,html,issue):
        images=load_images(ROOT,issue['items'])
        selected=[images[item['id']] for item in issue['items']]
        sources=[image for image in selected if not image['ai_generated']]
        self.assertEqual(html.count('data-image-kind="licensed-source"'),len(sources))
        self.assertEqual(html.count('data-image-kind="ai-illustration"'),len(selected)-len(sources))
        for source in sources:self.assert_source_credit(html,source)
        selected_ids={item['id'] for item in issue['items']}
        manifest=json.loads((ROOT/'daily/data/image-manifest.json').read_text())
        for source in manifest['images']:
            if not source['ai_generated'] and source['story_id'] not in selected_ids:
                self.assertNotIn(Path(source['path']).name,html)
                self.assertNotIn(source['license']['image_url'],html)

    def test_homepage_images_follow_latest_reviewed_edition(self):
        latest=max((json.loads(p.read_text()) for p in (ROOT/'daily/data/issues').glob('*.json')),key=lambda issue:issue['date'])
        generated=outputs()
        for name in ['daily/index.html','daily/en/index.html']:
            self.assert_edition_image_policy(generated[name],latest)

    def test_homepage_date_switch_keeps_source_credit_bound_to_selected_stories(self):
        config=json.loads((ROOT/'daily/config.json').read_text())
        historical=[json.loads(p.read_text()) for p in sorted((ROOT/'daily/data/issues').glob('*.json'),reverse=True)]
        # Rendering-only fixtures: these do not create or approve Oct9/10 news.
        # Exercise both a source-image edition and an all-AI-image edition.
        for fixture_date in ['2026-10-09','2026-10-10']:
            for content_date in ['2026-10-07','2026-10-08']:
                issue=copy.deepcopy(next(i for i in historical if i['date']==content_date))
                issue['date']=fixture_date
                issues=[issue]+[i for i in historical if i['date']!=fixture_date]
                for locale,page in [('zh-TW','daily/index.html'),('en','daily/en/index.html')]:
                    with self.subTest(date=fixture_date,content=content_date,locale=locale):
                        html=render_issue(issue,issues,copy.deepcopy(config),page,locale)
                        self.assert_edition_image_policy(html,issue)
                        self.assertIn(config['site_url']+'/daily/'+fixture_date+'/',html)

    def test_corrupt_svg_oversize_and_extreme_dimensions_refused(self):
        for fixture in (ROOT/'tests/newsletter/fixtures/images').iterdir():
            with self.assertRaises(ValueError, msg=fixture.name): validate_image(fixture)
        for dimensions in ((2048, 128), (128, 2048)):
            path = self.root/(str(dimensions[0])+'.jpg')
            Image.new('RGB', dimensions).save(path)
            self.assertEqual(validate_image(path)['height'], dimensions[1])
        large = self.root/'large.jpg'; Image.new('RGB', (2049, 2)).save(large)
        with self.assertRaisesRegex(ValueError, 'dimensions'): validate_image(large)
        large.write_bytes(b'x'*(MAX_IMAGE_BYTES+1))
        with self.assertRaisesRegex(ValueError, '300 KiB'): validate_image(large)
        good = self.root/'good.jpg'; Image.new('RGB', (100,100)).save(good)
        damaged = self.root/'damaged.jpg'; damaged.write_bytes(good.read_bytes()[:-25])
        with self.assertRaises(ValueError): validate_image(damaged)

    def test_manifest_paths_hashes_missing_story_and_provenance(self):
        shutil.copytree(ROOT/'daily', self.root/'daily')
        path = self.root/'daily/data/image-manifest.json'; baseline = json.loads(path.read_text())
        issue = json.loads((self.root/'daily/data/issues/2026-10-07.json').read_text())
        mutations = [lambda d:d['images'][0].update(path='../outside.jpg'),
                     lambda d:d['images'][0].update(sha256='0'*64),
                     lambda d:d['images'][0].update(width=200),
                     lambda d:d['images'][0].update(source_url='https://other.test/'),
                     lambda d:d['images'][0].update(ai_generated=False),
                     lambda d:d['images'][0]['alt'].pop('en'),
                     lambda d:d['images'].append(copy.deepcopy(d['images'][0]))]
        for mutate in mutations:
            value = copy.deepcopy(baseline); mutate(value); path.write_text(json.dumps(value))
            with self.assertRaises(ValueError): load_images(self.root, issue['items'])
        path.write_text(json.dumps(baseline))
        with self.assertRaisesRegex(ValueError, 'requires a verified image'):
            load_images(self.root, [{'id':'new-story','source_url':'https://source.test/'}])
        asset = self.root/baseline['images'][0]['path']; raw = asset.read_bytes(); asset.unlink()
        external = self.root/'outside.jpg'; external.write_bytes(raw); asset.symlink_to(external)
        with self.assertRaisesRegex(ValueError, 'symbolic'): load_images(self.root, issue['items'])

    def test_failed_image_validation_preserves_existing_outputs(self):
        shutil.copytree(ROOT/'daily', self.root/'daily')
        before = {p.relative_to(self.root):p.read_bytes() for p in (self.root/'daily').rglob('*.html')}
        (self.root/'daily/assets/stories/ironclad.jpg').write_bytes(b'broken')
        with self.assertRaises(ValueError): outputs(self.root)
        self.assertEqual(before, {p.relative_to(self.root):p.read_bytes() for p in (self.root/'daily').rglob('*.html')})

    def test_edition_budget_does_not_grow_with_historical_image_count(self):
        shutil.copytree(ROOT/'daily', self.root/'daily')
        path = self.root/'daily/data/image-manifest.json'; manifest = json.loads(path.read_text())
        original = copy.deepcopy(manifest['images'][5]); items = []
        for n in range(10):
            row = copy.deepcopy(original); row.update(story_id=f'budget-test-{n}',path=f'daily/assets/stories/budget-test-{n}.jpg')
            (self.root/row['path']).write_bytes((ROOT/original['path']).read_bytes())
            manifest['images'].append(row); items.append({'id':row['story_id'],'source_url':row['source_url']})
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, '2 MiB'): load_images(self.root, items)
        # A smaller edition remains valid even when historical assets share the manifest.
        self.assertIn(items[0]['id'], load_images(self.root, items[:2]))
        manifest['images'][0]['original_path']='/private/internal.png'; path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'unsupported metadata'): load_images(self.root, items[:2])

    def test_two_featured_remaining_compact_hidden_summaries_and_full_index(self):
        generated = outputs()
        issues = [json.loads(p.read_text()) for p in (ROOT/'daily/data/issues').glob('*.json')]
        latest = max(issues, key=lambda i:i['date'])
        for name in ('daily/index.html','daily/en/index.html','daily/2026-10-07/index.html','daily/2026-10-07/en/index.html'):
            html = generated[name]
            issue = next(i for i in issues if i['date']=='2026-10-07') if '/2026-10-07/' in name else latest
            count = len(issue['items'])
            self.assertEqual(html.count('class="headline-story featured-story"'), 2)
            self.assertEqual(html.count('class="headline-story compact-story"'), count-2)
            self.assertEqual(html.count('class="summary-fallback"'), count)
            self.assertNotIn('<details class="summary-fallback" open', html)
            self.assertIn(f'data-weekday="{date.fromisoformat(issue["date"]).weekday()}"', html)
            self.assertNotIn('<dialog open', html)
            self.assertEqual(html.count('data-summary-key='), count)
        index = json.loads(generated['daily/data/search-index.json'])
        self.assertEqual(len(index['records']), sum(len(i['items']) for i in issues))
        self.assertEqual(index['editions'], sorted([i['date'] for i in issues],reverse=True))
        for day in ('2026-10-04','2026-10-06'):
            self.assertNotIn('weekly-layouts.css', generated[f'daily/{day}/index.html'])
            self.assertNotIn('headline-story', generated[f'daily/{day}/index.html'])

    def test_script_json_is_data_and_summary_is_not_truncated(self):
        attack = '</script><script>alert(1)</script>&\u2028\u2029'
        escaped = script_json({'title':attack})
        self.assertNotIn('<', escaped); self.assertNotIn('&', escaped)
        self.assertEqual(json.loads(escaped)['title'], attack)
        issue = json.loads((ROOT/'daily/data/issues/2026-10-07.json').read_text())
        issue['items'][0]['en']['title'] = attack
        config = json.loads((ROOT/'daily/config.json').read_text())
        html = render_issue(issue,[issue],config,'daily/index.html','en')
        self.assertNotIn(attack,html); self.assertIn('&lt;script&gt;',html)
        for item in issue['items']: self.assertIn(item['zh-TW']['summary'],html)


if __name__ == '__main__': unittest.main()
