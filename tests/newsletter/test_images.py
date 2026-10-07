import copy
from datetime import date
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
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
        self.assertEqual(sum(i['bytes'] for i in selected), 1374494)
        self.assertEqual(images[issue['items'][1]['id']]['path'], 'daily/assets/stories/codex-local-tracing.jpg')

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
