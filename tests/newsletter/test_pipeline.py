import copy
from datetime import datetime, timezone
import hashlib
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/newsletter'))
from collect import collect
from create_draft import create_draft
from pipeline import prepare, preview, status, read_json, reviewed_errors, source_digest, source_files, run_path, write_file
from topics import validate_topic

NOW=datetime(2026,10,5,12,tzinfo=timezone.utc)
SOURCE={'id':'test','name':'Test source','category':'news','feed_url':'https://source.test/feed','allowed_hosts':['source.test']}
CONFIG={'sources':[SOURCE],'ranking':{'window_days':7,'target_items':10},'search':{'providers':['gdelt'],'max_results':100,'allowed_article_hosts':['source.test']}}

def feed(count=7):
    return ('<rss><channel>'+''.join(f'<item><title>AI story {i}</title><description>Research details {i}</description><link>https://source.test/{i}</link><pubDate>Sun, 04 Oct 2026 10:00:00 GMT</pubDate></item>' for i in range(count))+'</channel></rss>').encode()

def report(*,topic=False,partial=False,count=7):
    config=copy.deepcopy(CONFIG)
    if partial:config['sources'].append({**SOURCE,'id':'failed','feed_url':'https://source.test/fail'})
    def fetch(url):
        if url.endswith('/fail'):raise TimeoutError('test timeout')
        if url.startswith('https://api.gdeltproject.org/'):
            return b'{"articles":[]}'
        return feed(count)
    return collect(config,NOW,fetch,{'keywords':['AI']} if topic else None)

def approved(draft):
    issue=copy.deepcopy(draft)
    issue.update(reviewed=True,reviewed_on='2026-10-05')
    for field in ('title','coverage','editorial_note'):
        issue[field]={'zh-TW':'測試用編輯內容，僅限離線測試','en':'Synthetic editorial fixture for offline tests only'}
    for item in issue['items']:
        item['date_verification_required']=False
        for locale in ('zh-TW','en'):
            item[locale]={field:'Offline test editorial text' for field in ('title','summary','takeaway','caveat')}
    issue['discovery']['limitations_acknowledged']=True
    return issue

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.run=Path(self.temp.name)/'run'
    def make(self,*,topic=False,partial=False,count=7,allow_partial=False):
        r=report(topic=topic,partial=partial,count=count)
        config=copy.deepcopy(CONFIG)
        if partial:config['sources'].append({**SOURCE,'id':'failed','feed_url':'https://source.test/fail'})
        return prepare(self.run,config=config,topic=r['topic'],issue_date='2026-10-05',candidate_report=r,now=NOW,allow_partial=allow_partial)
    def write_review(self,mutate=None):
        value=approved(read_json(self.run/'draft.json'))
        if mutate:mutate(value)
        (self.run/'draft.json').write_text(json.dumps(value))
        return value
    def test_general_draft_support_without_topic_search(self):
        state=self.make();self.assertEqual(state['state'],'awaiting_editorial_review')
        draft=read_json(self.run/'draft.json');self.assertEqual(draft['topic']['keywords'],[])
        self.assertIn('source_evidence',draft['items'][0]);self.assertFalse(draft['reviewed'])
        self.assertEqual(draft['discovery']['search_status'],'not_requested')
    def test_general_partial_requires_explicit_acknowledgement(self):
        state=self.make(partial=True);self.assertEqual(state['state'],'blocked_collection')
        self.assertFalse((self.run/'draft.json').exists())
        state=prepare(self.run,resume=True,allow_partial=True)
        self.assertEqual(state['state'],'awaiting_editorial_review');self.assertTrue(state['partial_collection_accepted'])
    def test_topic_partial_resume_keeps_original_snapshot_without_network(self):
        state=self.make(topic=True,partial=True);before=(self.run/'candidates.json').read_bytes()
        state=prepare(self.run,resume=True,allow_partial=True,fetch=lambda url:self.fail('resume must not fetch'))
        self.assertEqual(state['state'],'awaiting_editorial_review');self.assertEqual((self.run/'candidates.json').read_bytes(),before)
    def test_idempotent_resume_preserves_editor_edits(self):
        self.make();(self.run/'draft.json').write_text('user editing in progress')
        state=prepare(self.run,resume=True,fetch=lambda url:self.fail('must not fetch'))
        self.assertEqual(state['state'],'awaiting_editorial_review');self.assertEqual((self.run/'draft.json').read_text(),'user editing in progress')
    def test_prepare_calls_real_collector_interface_once(self):
        calls=[]
        state=prepare(self.run,config=CONFIG,topic=validate_topic(),issue_date='2026-10-05',now=NOW,fetch=lambda url:(calls.append(url) or feed()))
        self.assertEqual(state['state'],'awaiting_editorial_review');self.assertEqual(calls,['https://source.test/feed'])
        prepare(self.run,resume=True,fetch=lambda url:self.fail('must not fetch'))
    def test_wrong_report_date_or_topic_blocks_without_draft(self):
        for change in ('date','topic'):
            with self.subTest(change=change):
                r=report();r['generated_at']='2026-10-04T12:00:00Z' if change=='date' else r['generated_at']
                if change=='topic':r['topic']=validate_topic({'keywords':['AI']})
                target=Path(self.temp.name)/change
                state=prepare(target,config=CONFIG,topic=validate_topic(),issue_date='2026-10-05',candidate_report=r,now=NOW)
                self.assertEqual(state['state'],'blocked_collection');self.assertFalse((target/'draft.json').exists())
    def test_insufficient_results_and_total_search_failure_never_pad(self):
        state=self.make(count=5);self.assertEqual(state['state'],'blocked_collection')
        self.assertFalse((self.run/'draft.json').exists())
        r=report(topic=True);r['search_status']='failed';r['status']='partial';r['searches'][0]['status']='failed';r['failures']=[{'source_id':'gdelt','error':'Test failure'}]
        target=Path(self.temp.name)/'failed'
        state=prepare(target,config=CONFIG,topic=r['topic'],issue_date='2026-10-05',candidate_report=r,now=NOW,allow_partial=True)
        self.assertEqual(state['state'],'blocked_collection');self.assertFalse((target/'draft.json').exists())
    def test_unreviewed_draft_cannot_preview(self):
        self.make();state=preview(self.run)
        self.assertEqual(state['state'],'blocked_review');self.assertFalse((self.run/'preview').exists())
        self.write_review();self.assertEqual(preview(self.run)['state'],'preview_ready')
    def test_general_end_to_end_preview_is_isolated_and_reproducible(self):
        before=source_digest(ROOT);self.make();self.write_review()
        state=preview(self.run);self.assertEqual(state['state'],'preview_ready')
        self.assertFalse(state['published']);self.assertFalse(state['email_sent']);self.assertFalse(state['schedule_active'])
        self.assertFalse((ROOT/'daily/data/issues/2026-10-05.json').exists())
        self.assertEqual(source_digest(ROOT),before)
        html=(self.run/'preview/daily/2026-10-05/en/index.html').read_text()
        self.assertIn('General AI edition',html);self.assertNotIn('id="subscription"',html)
        self.assertEqual(preview(self.run),state);self.assertEqual(status(self.run)['state'],'preview_ready')
        self.assertFalse((self.run/'preview/.atm').exists());self.assertFalse((self.run/'preview/scripts').exists())
        image='daily/assets/stories/codex-local-tracing.jpg'
        self.assertEqual((self.run/'preview'/image).read_bytes(),(ROOT/image).read_bytes())
        for image in ['daily/assets/stories/simon-datasette-parsable-2048.webp','daily/assets/licenses/LICENSE-APACHE-2.0.txt','daily/assets/licenses/SIMON-IMAGE-NOTICE.txt']:
            self.assertEqual((self.run/'preview'/image).read_bytes(),(ROOT/image).read_bytes())
        self.assertTrue((self.run/'preview/daily/data/search-index.json').is_file())
    def test_image_bytes_and_validation_logic_are_bound_to_source_digest(self):
        files=source_files(ROOT)
        self.assertIn('scripts/newsletter/image_policy.py',files)
        manifest=json.loads((ROOT/'daily/data/image-manifest.json').read_text())
        self.assertTrue({image['path'] for image in manifest['images']}.issubset(files))
        with patch('pipeline.source_files',return_value={**files,'daily/assets/stories/ironclad.jpg':'0'*64}):
            altered=source_digest(ROOT)
        self.assertNotEqual(source_digest(ROOT),altered)
    def test_enhanced_edition_requires_image_onboarding_then_new_immutable_run(self):
        root=Path(self.temp.name)/'fixture-source';root.mkdir()
        shutil.copytree(ROOT/'daily',root/'daily')
        shutil.copytree(ROOT/'scripts/newsletter',root/'scripts/newsletter',ignore=shutil.ignore_patterns('__pycache__'))
        (root/'daily/data/issues/2026-10-07.json').unlink()  # Disposable pre-publication fixture only.
        now=datetime(2026,10,7,12,tzinfo=timezone.utc)
        xml=feed().replace(b'Sun, 04 Oct 2026',b'Tue, 06 Oct 2026')
        r=collect(CONFIG,now,lambda url:xml)
        def prepare_and_review(target):
            state=prepare(target,root=root,config=CONFIG,topic=r['topic'],issue_date='2026-10-07',candidate_report=r,now=now)
            self.assertEqual(state['state'],'awaiting_editorial_review')
            self.assertEqual(preview(target,root=root)['state'],'blocked_review')
            issue=approved(read_json(target/'draft.json'));issue['reviewed_on']='2026-10-07'
            for item in issue['items']:item['zh-TW']['summary']='測'*500
            (target/'draft.json').write_text(json.dumps(issue))
            return issue
        first=Path(self.temp.name)/'before-images';issue=prepare_and_review(first)
        with self.assertRaisesRegex(ValueError,'requires a verified image'):preview(first,root=root)
        self.assertFalse((first/'preview').exists())
        manifest_path=root/'daily/data/image-manifest.json';manifest=read_json(manifest_path)
        originals=copy.deepcopy(manifest['images'])
        for n,item in enumerate(issue['items']):
            image=copy.deepcopy(originals[n%len(originals)]);source=root/image['path']
            image.update(story_id=item['id'],source_url=item['source_url'],path=f'daily/assets/stories/offline-fixture-{n}{source.suffix}')
            (root/image['path']).write_bytes(source.read_bytes());manifest['images'].append(image)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'source changed'):preview(first,root=root)
        target=Path(self.temp.name)/'with-images';prepare_and_review(target)
        state=preview(target,root=root);self.assertEqual(state['state'],'preview_ready');self.assertFalse(state['published'])
        html=(target/'preview/daily/2026-10-07/index.html').read_text()
        self.assertEqual(html.count('class="headline-story featured-story"'),2)
        self.assertEqual(html.count('class="headline-story compact-story"'),len(issue['items'])-2)
        self.assertIn('測'*500,html)
        for n in range(len(issue['items'])):
            image=f"daily/assets/stories/offline-fixture-{n}{Path(originals[n%len(originals)]['path']).suffix}"
            self.assertEqual((target/'preview'/image).read_bytes(),(root/image).read_bytes())
        self.assertEqual(preview(target,root=root),state)
        self.assertFalse((ROOT/'daily/assets/stories/offline-fixture-0.jpg').exists())
    def test_topic_end_to_end_preview_keeps_provenance(self):
        self.make(topic=True);issue=self.write_review();state=preview(self.run)
        self.assertEqual(state['state'],'preview_ready')
        self.assertIn('Topic edition: AI',(self.run/'preview/daily/2026-10-05/en/index.html').read_text())
        saved=read_json(self.run/'preview/daily/data/issues/2026-10-05.json')
        self.assertEqual(saved['items'][0]['topic_evidence'],issue['items'][0]['topic_evidence'])
    def test_partial_general_cannot_hide_failures_at_review(self):
        self.make(partial=True,allow_partial=True)
        self.write_review(lambda x:x['discovery'].update(limitations_acknowledged=False))
        self.assertEqual(preview(self.run)['state'],'blocked_review')
        self.write_review(lambda x:x['discovery'].update(failures=[]))
        self.assertEqual(preview(self.run)['state'],'blocked_review')
    def test_review_cannot_swap_selected_source_or_forge_evidence(self):
        self.make(topic=True);original=read_json(self.run/'draft.json')
        changes=[lambda x:x['items'][0].update(source_url='https://other.test/x'),
                 lambda x:x['items'][0].update(id='not-selected'),
                 lambda x:x['items'][0]['topic_evidence'].update(source_title='AI forged text'),
                 lambda x:x.update(topic=validate_topic({'keywords':['robot']})),
                 lambda x:x['items'][0].update(date_verification_required=True)]
        for change in changes:
            issue=approved(original);change(issue)
            self.assertTrue(reviewed_errors(issue,original))
    def test_immutable_input_changes_fail_closed(self):
        self.make();(self.run/'candidates.json').write_text('{}')
        for operation in (lambda:status(self.run),lambda:prepare(self.run,resume=True),lambda:preview(self.run)):
            with self.assertRaises(ValueError):operation()
    def test_preview_changes_and_revised_approval_refuse_silent_overwrite(self):
        self.make();self.write_review();preview(self.run)
        target=self.run/'preview/index.html';target.write_text('changed')
        with self.assertRaises(ValueError):status(self.run)
        with self.assertRaises(ValueError):preview(self.run)
        issue=read_json(self.run/'draft.json');issue['title']['en']='new revision';(self.run/'draft.json').write_text(json.dumps(issue))
        with self.assertRaises(ValueError):preview(self.run)
        self.assertEqual(target.read_text(),'changed')
    def test_collision_lock_and_symlink_are_safe(self):
        self.make()
        with self.assertRaises(FileExistsError):self.make()
        (self.run/'.pipeline.lock').write_text('another process')
        with self.assertRaises(ValueError):prepare(self.run,resume=True)
        self.assertEqual((self.run/'.pipeline.lock').read_text(),'another process')
        link=Path(self.temp.name)/'alias';link.symlink_to(self.run,target_is_directory=True)
        with self.assertRaises(ValueError):status(link)
    def test_run_directory_cannot_be_public_repository_path(self):
        with self.assertRaises(ValueError):prepare(ROOT/'daily/unsafe-run',config=CONFIG,now=NOW)
        self.assertFalse((ROOT/'daily/unsafe-run').exists())
    def test_traversal_confinement_uses_canonical_path(self):
        disguised=ROOT.parent/'temporary'/'..'/ROOT.name/'daily/pipeline-output'
        with self.assertRaises(ValueError):run_path(disguised)
        legitimate=ROOT/'../pipeline-smoke/outside'
        self.assertEqual(run_path(legitimate),legitimate.resolve())
        self.assertFalse((ROOT/'daily/pipeline-output').exists())
    def test_resume_cannot_replace_inputs(self):
        self.make()
        with self.assertRaises(ValueError):prepare(self.run,resume=True,topic=validate_topic({'keywords':['new']}))
    def test_general_lookback_uses_collection_window(self):
        r=report();r['ranking']['window_days']=14
        for item in r['candidates']:item['published_at']='2026-09-25T12:00:00Z'
        self.assertEqual(len(create_draft(r,'2026-10-05')['items']),7)
    def test_atomic_no_clobber_preserves_concurrent_editor_file(self):
        import os
        target=Path(self.temp.name)/'output.json';original=os.link
        def competing_writer(src,dst):
            Path(dst).write_text('concurrent editor content')
            return original(src,dst)
        with patch('pipeline.os.link',side_effect=competing_writer):
            with self.assertRaises(FileExistsError):write_file(target,b'pipeline content')
        self.assertEqual(target.read_text(),'concurrent editor content')
    def test_incomplete_hash_manifest_is_rejected(self):
        self.make();state=read_json(self.run/'run.json');state['input_hashes'].pop('candidates.json')
        (self.run/'run.json').write_text(json.dumps(state));(self.run/'candidates.json').write_text('{}')
        with self.assertRaises(ValueError):status(self.run)
        with self.assertRaises(ValueError):preview(self.run)
    def test_imported_sources_and_queries_must_match_snapshot(self):
        r=report();config=copy.deepcopy(CONFIG);config['sources'][0]['feed_url']='https://other.test/feed';config['sources'][0]['allowed_hosts']=['other.test']
        state=prepare(self.run,config=config,topic=r['topic'],issue_date='2026-10-05',candidate_report=r,now=NOW)
        self.assertEqual(state['state'],'blocked_collection');self.assertFalse((self.run/'draft.json').exists())
        r=report(topic=True);r['searches'][0]['query']='different'
        state=prepare(Path(self.temp.name)/'query',config=CONFIG,topic=r['topic'],issue_date='2026-10-05',candidate_report=r,now=NOW)
        self.assertEqual(state['state'],'blocked_collection')
    def test_general_review_cannot_escape_time_window(self):
        self.make();selection=read_json(self.run/'selection.json');issue=approved(selection)
        issue['items'][0]['published_date']='2000-01-01'
        self.assertTrue(reviewed_errors(issue,selection))
        issue['collection_window_days']=9999
        self.assertTrue(reviewed_errors(issue,selection))
    def test_historical_live_or_existing_date_stops_before_network(self):
        for day in ('2026-10-03','2026-10-04'):
            with self.assertRaises(ValueError):prepare(Path(self.temp.name)/day,config=CONFIG,issue_date=day,now=NOW,fetch=lambda url:self.fail('must not fetch'))
        with self.assertRaises(ValueError):prepare(self.run,config=CONFIG,issue_date='2026-10-04',candidate_report=report(),now=NOW)
    def test_import_cannot_remove_required_coverage_warnings(self):
        topic=validate_topic({'keywords':['AI','中文']})
        r=collect(CONFIG,NOW,lambda url:b'{"articles":[]}' if 'gdeltproject' in url else feed(),topic)
        self.assertEqual(r['coverage_warnings'][0]['code'],'needs_english_alias')
        r['coverage_warnings']=[];r['status']='collected';r['search_status']='completed'
        state=prepare(self.run,config=CONFIG,topic=topic,issue_date='2026-10-05',candidate_report=r,now=NOW)
        self.assertEqual(state['state'],'blocked_collection')
    def test_import_cannot_hide_result_limit_or_failed_receipt(self):
        r=report(topic=True);r['searches'][0]['received']=100
        state=prepare(self.run,config=CONFIG,topic=r['topic'],issue_date='2026-10-05',candidate_report=r,now=NOW)
        self.assertEqual(state['state'],'blocked_collection')
        config=copy.deepcopy(CONFIG);config['search']['providers']=['gdelt','arxiv']
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"/>'
        r=collect(config,NOW,lambda url:xml if 'export.arxiv.org' in url else b'{"articles":[]}' if 'gdeltproject' in url else feed(),{'keywords':['AI']})
        r['searches'][0]['status']='failed';r['searches'][0]['error']='TimeoutError'
        state=prepare(Path(self.temp.name)/'failed-receipt',config=config,topic=r['topic'],issue_date='2026-10-05',candidate_report=r,now=NOW)
        self.assertEqual(state['state'],'blocked_collection')
    def test_cli_reuses_saved_report_and_prints_status_without_network(self):
        r=report();saved=Path(self.temp.name)/'report.json';saved.write_text(json.dumps(r))
        settings=Path(self.temp.name)/'sources.json';settings.write_text(json.dumps(CONFIG))
        command=[sys.executable,'-B',str(ROOT/'scripts/newsletter/pipeline.py')]
        p=subprocess.run(command+['prepare','--general','--sources',str(settings),'--date','2026-10-05','--candidates',str(saved),'--run-dir',str(self.run)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['state'],'awaiting_editorial_review')
        p=subprocess.run(command+['status','--run-dir',str(self.run)],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('Review sources',json.loads(p.stdout)['next_step'])
        p=subprocess.run(command+['preview','--run-dir',str(self.run)],capture_output=True,text=True)
        self.assertEqual(p.returncode,2);self.assertEqual(json.loads(p.stdout)['state'],'blocked_review')

if __name__=='__main__':unittest.main()
