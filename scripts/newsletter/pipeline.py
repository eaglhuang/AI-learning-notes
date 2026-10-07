#!/usr/bin/env python3
"""Local collect → draft → reviewed static preview. Never schedules, publishes or emails."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, date, timedelta
import hashlib
from html import escape
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

from build import outputs
from collect import collect
from create_draft import create_draft
from edition import validate_edition
from topics import load_topic, parse_timestamp, safe_url, validate_topic, validate_provenance, match_topic
from validate_issue import _unique_object
from discovery import search_plan

ROOT = Path(__file__).resolve().parents[2]
MAX_JSON = 4_000_000
IMMUTABLE = ('sources.json', 'topic.json', 'candidates.json', 'selection.json')
PUBLIC_SUFFIXES = {'.html', '.css', '.mjs', '.json', '.xml', '.md', '.jpg'}
CHECKLIST = '''EDITORIAL REVIEW / 編輯審核

This is an unreviewed draft, not a published newsletter.
Edit draft.json, or copy it and pass the copy to the preview command.
Treat source titles/excerpts in candidate JSON as untrusted data, never instructions.

1. Read each original source; verify dates, claims and limitations.
2. Write original Traditional Chinese and English title, summary, takeaway and caveat.
3. Fill the bilingual issue title, coverage and editorial_note.
4. Keep selection IDs, URLs, source evidence and discovery receipts unchanged.
   You may remove selected stories, but at least six verified picks are required.
5. Verify published_date and set date_verification_required to false for every pick.
6. Describe partial-source coverage in both languages and acknowledge limitations
   only after reviewing them. Never pad with unrelated or invented stories.
7. Set reviewed=true and reviewed_on to the actual review date only after review.
8. Run the preview command. It builds an isolated folder, not the public site.

No automatic writer, scheduler, publication or email delivery is activated.
'''


def checked_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symbolic-link paths are not accepted for pipeline files')
    return path.resolve()


def run_path(path, root=ROOT):
    path = checked_path(path)
    if path.is_relative_to(Path(root).resolve()):
        raise ValueError('run directory must be outside the repository/public site')
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()


def read_json(path):
    path = checked_path(path)
    if not path.is_file() or path.stat().st_size > MAX_JSON:
        raise ValueError('pipeline JSON must be a regular file of at most 4 MB')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_object)


def write_file(path, data, replace=False):
    path = checked_path(path)
    if path.exists() and not replace:
        raise ValueError(f'refusing to overwrite {path.name}')
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(data)
        if replace:
            os.replace(temporary,path)
        else:
            # Same-directory hard link is an atomic no-clobber publish.
            # Unsupported filesystems fail closed rather than falling back to overwrite.
            os.link(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked(run):
    lock = checked_path(run/'.pipeline.lock')
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError:
        raise ValueError('run is locked or interrupted; inspect it before using a new run directory')
    try:
        handle.write('Local pipeline operation in progress\n'); handle.close()
        yield
    finally:
        lock.unlink(missing_ok=True)


def source_files(root):
    files = [p for p in (root/'daily').rglob('*') if p.is_file() and p.suffix in PUBLIC_SUFFIXES]
    files += [root/'scripts/newsletter'/name for name in ('build.py','image_policy.py','edition.py','topics.py','validate_issue.py','pipeline.py','create_draft.py','collect.py','discovery.py')]
    result = {}
    for path in files:
        path = checked_path(path)
        if path.stat().st_size > MAX_JSON:
            raise ValueError('preview source file is too large')
        result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def source_digest(root):
    return digest(encoded(source_files(root)))


def save_run(run, state):
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    write_file(run/'run.json', encoded(state), replace=True)


def load_run(run):
    state = read_json(run/'run.json')
    if not isinstance(state, dict) or type(state.get('schema_version')) is not int or state['schema_version'] != 1:
        raise ValueError('unsupported pipeline run')
    if state.get('state') not in ('collecting','blocked_collection','awaiting_editorial_review','blocked_review','preview_ready'):
        raise ValueError('unsupported pipeline state')
    date.fromisoformat(state['date'])
    hashes = state.get('input_hashes')
    if not isinstance(hashes, dict) or set(hashes) - set(IMMUTABLE):
        raise ValueError('invalid run input manifest')
    required = set(IMMUTABLE) if state['state'] in ('awaiting_editorial_review','blocked_review','preview_ready') else {'sources.json','topic.json'}
    allowed_sets = [required] if len(required)==4 else [required, required|{'candidates.json'}]
    if set(hashes) not in allowed_sets:
        raise ValueError('run input manifest is incomplete for its state')
    if any(state.get(key) is not False for key in ('published','email_sent','schedule_active')) or state.get('review_required') is not True:
        raise ValueError('run cannot claim external activation or bypass review')
    for name, sha in hashes.items():
        if not isinstance(sha,str) or digest(checked_path(run/name).read_bytes()) != sha:
            raise ValueError(f'immutable input changed: {name}; preserve edits and start a new run')
    return state


def snapshot(run, state, name, value):
    data = encoded(value)
    if len(data) > MAX_JSON: raise ValueError('pipeline snapshot exceeds 4 MB')
    write_file(run/name, data)
    state['input_hashes'][name] = digest(data)


def check_report(report, topic, issue_date, config):
    if not isinstance(report,dict) or type(report.get('schema_version')) is not int or report['schema_version'] != 1:
        raise ValueError('unsupported candidate report')
    if validate_topic(report.get('topic')) != topic:
        raise ValueError('candidate report does not match the chosen topic configuration')
    if report.get('mode') != ('topic' if topic['keywords'] else 'general'):
        raise ValueError('candidate report mode does not match topic configuration')
    stamp = parse_timestamp(report.get('generated_at')).astimezone(timezone.utc)
    if stamp.date().isoformat() != issue_date:
        raise ValueError('candidate report UTC date must match the run date; use a fresh collection for another day')
    if not isinstance(report.get('candidates'),list):
        raise ValueError('candidate report requires an array')

    ranking=report.get('ranking')
    expected_days=topic['lookback_days'] if topic['keywords'] else config['ranking']['window_days']
    if not isinstance(ranking,dict) or type(ranking.get('window_days')) is not int or ranking['window_days']!=expected_days:
        raise ValueError('candidate report lookback does not match source/topic settings')
    sources={}
    for source in config['sources']:
        if source['id'] in sources: raise ValueError('duplicate source IDs')
        safe_url(source['feed_url'],source['allowed_hosts'])
        sources[source['id']]=source
    plans,required_warnings=search_plan(topic,config.get('search',{}),stamp) if topic['keywords'] else ([],[])
    searches={p['provider']:p for p in plans}
    if set(sources)&set(searches):
        raise ValueError('fixed source IDs must not shadow search-provider IDs')
    receipts=report.get('searches')
    if not isinstance(receipts,list) or {q.get('provider') for q in receipts if isinstance(q,dict)}!=set(searches) or len(receipts)!=len(searches):
        raise ValueError('candidate report does not retain exactly the configured search receipts')
    def verify_record(record):
        validate_provenance(record)
        if parse_timestamp(record['retrieved_at'])!=stamp:
            raise ValueError('provenance timestamp does not match this collection')
        if record['provider']=='rss':
            source=sources.get(record.get('source_id'))
            if not source or safe_url(record['request_url'])!=safe_url(source['feed_url']):
                raise ValueError('RSS provenance does not match the configured source')
            return source['allowed_hosts']
        plan=searches.get(record['provider'])
        if not plan or record['request_url']!=plan['request_url'] or record['query']!=plan['query']:
            raise ValueError('search provenance does not match the configured query/provider')
        return plan['allowed_hosts']
    for receipt in receipts:
        verify_record(receipt)
        if receipt.get('status') not in ('ok','failed'):
            raise ValueError('invalid search receipt status')
        if receipt.get('limit')!=searches[receipt['provider']]['limit']:
            raise ValueError('search receipt limit differs from configured request')
        if receipt['status']=='ok' and (type(receipt.get('received')) is not int or not 0<=receipt['received']<=receipt['limit']):
            raise ValueError('successful search receipt requires a bounded result count')
    failures,warnings=report.get('failures'),report.get('coverage_warnings')
    if not isinstance(failures,list) or not isinstance(warnings,list):
        raise ValueError('collection diagnostics must be retained as arrays')
    if any(not isinstance(f,dict) or f.get('source_id') not in set(sources)|set(searches) for f in failures):
        raise ValueError('failure receipt does not match configured sources')
    if any(not isinstance(w,dict) for w in warnings) or any(w not in warnings for w in required_warnings):
        raise ValueError('required search-planning coverage warnings are missing')
    failed_ids={f['source_id'] for f in failures}
    for receipt in receipts:
        if receipt['status']=='failed' and receipt['provider'] not in failed_ids:
            raise ValueError('failed search receipt cannot be hidden from failure diagnostics')
        capped=receipt.get('received',0)>=receipt['limit'] or receipt.get('more_results_available') is True
        if capped and not any(w.get('provider')==receipt['provider'] and w.get('code')=='result_limit' for w in warnings):
            raise ValueError('bounded search result-limit warning is missing')
    expected_status='partial' if failures or warnings else 'collected'
    expected_search='not_requested' if not topic['keywords'] else ('failed' if not any(q['status']=='ok' for q in receipts) else 'partial' if failures or warnings else 'completed')
    if report.get('status')!=expected_status or report.get('search_status')!=expected_search:
        raise ValueError('collection status contradicts retained diagnostics')
    for candidate in report['candidates']:
        if not isinstance(candidate,dict) or not all(isinstance(candidate.get(k),str) for k in ('title','source_excerpt','source_id','source','category')):
            raise ValueError('malformed candidate metadata')
        records=candidate.get('provenance')
        if not isinstance(records,list) or not 1<=len(records)<=16:
            raise ValueError('candidate provenance is missing')
        for record in records:
            safe_url(candidate['source_url'],verify_record(record))
        first=records[0]
        if first['provider']=='rss':
            origin=sources[first['source_id']]
            expected=(origin['id'],origin['name'],origin['category'])
        elif first['provider']=='arxiv': expected=('arxiv-search','arXiv','papers')
        else:
            from urllib.parse import urlsplit
            expected=('gdelt',urlsplit(candidate['source_url']).hostname,'news')
        if (candidate['source_id'],candidate['source'],candidate['category'])!=expected:
            raise ValueError('candidate source identity contradicts its provenance')
        match=match_topic(candidate['title'],candidate['source_excerpt'],topic)
        if not match['eligible'] or any(candidate.get(k)!=match[k] for k in ('matched_keywords','matched_terms')):
            raise ValueError('candidate keyword evidence does not verify')


def prepare(run_dir, *, config=None, topic=None, issue_date=None, resume=False,
            allow_partial=False, candidate_report=None, root=ROOT, fetch=None, now=None):
    root = Path(root).resolve(); run = run_path(run_dir, root)
    now = now or datetime.now(timezone.utc)
    if resume:
        if any(value is not None for value in (config,topic,issue_date,candidate_report)):
            raise ValueError('resume uses its existing input snapshots; do not supply replacement inputs')
        if not run.is_dir():
            raise ValueError('run does not exist')
    else:
        topic = validate_topic(topic) if topic is not None else validate_topic()
        issue_date = issue_date or now.date().isoformat()
        if not isinstance(issue_date,str) or date.fromisoformat(issue_date).isoformat()!=issue_date:
            raise ValueError('run date must use YYYY-MM-DD')
        if date.fromisoformat(issue_date) > now.date():
            raise ValueError('run date cannot be in the future')
        if config is None:
            raise ValueError('source configuration is required')
        if candidate_report is None and issue_date!=now.date().isoformat():
            raise ValueError('live collection must use today UTC; use a saved report for historical runs')
        if (root/'daily/data/issues'/f'{issue_date}.json').exists():
            raise ValueError('an edition already exists for this date; use a separate correction workflow')
        run.mkdir(parents=True, exist_ok=False)
    with locked(run):
        if resume:
            state = load_run(run)
            if state['source_digest'] != source_digest(root):
                raise ValueError('preview source changed since preparation; start a new run')
            if state['state'] in ('awaiting_editorial_review','blocked_review','preview_ready'):
                return status(run, root=root)
            if 'candidates.json' not in state['input_hashes']:
                raise ValueError('collection was interrupted; use a new run directory, never an implicit network retry')
            report = read_json(run/'candidates.json'); topic = read_json(run/'topic.json'); config = read_json(run/'sources.json')
        else:
            state = {'schema_version':1,'date':issue_date,'mode':'topic' if topic['keywords'] else 'general',
                     'state':'collecting','input_hashes':{},'source_digest':source_digest(root),'errors':[],
                     'review_required':True,'preview':None,'published':False,'email_sent':False,'schedule_active':False}
            snapshot(run,state,'sources.json',config); snapshot(run,state,'topic.json',topic)
            save_run(run,state)
            try:
                report = candidate_report if candidate_report is not None else collect(config,now=now,fetch=fetch,topic=topic)
                check_report(report,topic,issue_date,config)
                snapshot(run,state,'candidates.json',report)
            except (ValueError,KeyError,TypeError,OSError) as error:
                state.update(state='blocked_collection',errors=[str(error)])
                save_run(run,state); return state
        try:
            check_report(report,topic,state['date'],config)
            draft = create_draft(report,state['date'],allow_partial=allow_partial)
        except (ValueError,KeyError,TypeError,OSError) as error:
            state.update(state='blocked_collection',errors=[str(error)])
            save_run(run,state); return state
        snapshot(run,state,'selection.json',draft)
        write_file(run/'draft.json',encoded(draft))
        write_file(run/'EDITORIAL-CHECKLIST.txt',CHECKLIST.encode())
        state.update(state='awaiting_editorial_review',errors=[],candidate_count=len(report['candidates']),
                     selected_count=len(draft['items']),partial_collection_accepted=bool(allow_partial))
        save_run(run,state)
        return state


def reviewed_errors(issue, selection):
    errors = validate_edition(issue)
    if not isinstance(issue,dict): return errors
    if issue.get('date') != selection['date'] or issue.get('topic') != selection['topic'] or issue.get('collection_window_days') != selection['collection_window_days']:
        errors.append('reviewed edition date/topic must match this prepared run')
    if not isinstance(issue.get('discovery'),dict):
        return errors + ['discovery metadata must be retained']
    before = dict(selection['discovery']); after = dict(issue['discovery'])
    before.pop('limitations_acknowledged',None); after.pop('limitations_acknowledged',None)
    if before != after:
        errors.append('discovery receipts and coverage diagnostics must remain unchanged')
    partial = selection['discovery']['search_status']=='partial' or bool(selection['discovery']['failures'])
    if partial and issue.get('discovery',{}).get('limitations_acknowledged') is not True:
        errors.append('acknowledge the known partial collection after describing it in both languages')
    original = {item['id']:item for item in selection['items']}
    for item in issue.get('items',[]) if isinstance(issue.get('items'),list) else []:
        if not isinstance(item,dict): continue
        selected = original.get(item.get('id')) if isinstance(item.get('id'),str) else None
        if selected is None:
            errors.append('reviewed items must come from this prepared selection'); continue
        for field in ('source_url','source','category','topic_evidence','source_evidence'):
            if item.get(field) != selected.get(field):
                errors.append(f"{item['id']}: selected source identity/evidence changed ({field})")
        try:
            published=date.fromisoformat(item.get('published_date'))
            if published<date.fromisoformat(selection['date'])-timedelta(days=selection['collection_window_days']):
                errors.append(f"{item['id']}: publication date is outside the prepared collection window")
        except (TypeError,ValueError): pass
        if item.get('date_verification_required') is not False:
            errors.append(f"{item['id']}: explicitly verify the publication date")
    return errors


def verify_preview(run, state):
    manifest = read_json(run/'preview-manifest.json')
    if not isinstance(manifest,dict) or not isinstance(manifest.get('files'),dict) or manifest.get('reviewed_sha256') != state['reviewed_sha256']:
        raise ValueError('preview manifest is invalid')
    if not {'index.html','daily/index.html','daily/en/index.html'}.issubset(manifest['files']):
        raise ValueError('preview manifest is incomplete')
    if digest(encoded(read_json(run/'reviewed-input.json'))) != state['reviewed_sha256']:
        raise ValueError('reviewed input snapshot changed')
    actual = {p.relative_to(run/'preview').as_posix() for p in (run/'preview').rglob('*') if p.is_file()}
    if actual != set(manifest['files']):
        raise ValueError('preview file inventory changed')
    for name, sha in manifest['files'].items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or rel.as_posix()!=name:
            raise ValueError('unsafe preview manifest path')
        path = checked_path(run/'preview'/rel)
        if not path.is_file() or digest(path.read_bytes()) != sha:
            raise ValueError('preview files changed or are missing; preserve the run and regenerate separately')
    return manifest


def preview(run_dir, *, reviewed_file=None, root=ROOT):
    root = Path(root).resolve(); run = run_path(run_dir,root)
    with locked(run):
        state = load_run(run)
        if 'selection.json' not in state['input_hashes']:
            raise ValueError('this run has no reviewable selection')
        if state['source_digest'] != source_digest(root):
            raise ValueError('preview source changed since preparation; start a new run')
        reviewed_file = checked_path(reviewed_file or run/'draft.json')
        issue = read_json(reviewed_file); reviewed_hash = digest(encoded(issue))
        if state['state']=='preview_ready':
            if state['reviewed_sha256'] != reviewed_hash:
                raise ValueError('reviewed content changed after preview; retain this preview and start a new run')
            verify_preview(run,state); return state
        errors = reviewed_errors(issue,read_json(run/'selection.json'))
        existing = root/'daily/data/issues'/f"{state['date']}.json"
        if existing.exists():
            errors.append('an edition already exists for this date; correction/replacement is a separate reviewed action')
        if errors:
            state.update(state='blocked_review',errors=errors)
            save_run(run,state); return state
        if (run/'preview').exists():
            raise ValueError('an interrupted preview exists; preserve it and use a new run')
        with tempfile.TemporaryDirectory(prefix='.preview-',dir=run) as tmp:
            stage = Path(tmp)
            for name in source_files(root):
                if not name.startswith('daily/'): continue
                target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(checked_path(root/name),target)
            preview_config=read_json(stage/'daily/config.json')
            preview_config['subscription']['enabled']=False
            write_file(stage/'daily/config.json',encoded(preview_config),replace=True)
            issue_path=stage/'daily/data/issues'/f"{issue['date']}.json"
            write_file(issue_path,encoded(issue))
            for name,content in outputs(stage).items():
                target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
                write_file(target,content.encode(),replace=True)
            site=safe_url(read_json(stage/'daily/config.json')['site_url'])
            landing=f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Local newsletter preview</title><h1>Local newsletter preview</h1><p>Not published or emailed.</p><p><a href="daily/{issue["date"]}/">繁中</a> · <a href="daily/{issue["date"]}/en/">English</a></p><p><a href="{escape(site,quote=True)}">Public main site</a></p></html>\n'
            write_file(stage/'index.html',landing.encode())
            files={p.relative_to(stage).as_posix():digest(p.read_bytes()) for p in stage.rglob('*') if p.is_file()}
            write_file(run/'reviewed-input.json',encoded(issue))
            write_file(run/'preview-manifest.json',encoded({'schema_version':1,'reviewed_sha256':reviewed_hash,'files':files}))
            os.rename(stage,run/'preview')
        state.update(state='preview_ready',errors=[],reviewed_sha256=reviewed_hash,
                     preview='preview/index.html',preview_file_count=len(files))
        save_run(run,state)
        return state


def status(run_dir, *, root=ROOT):
    run=run_path(run_dir,root);state=load_run(run)
    if state['source_digest'] != source_digest(Path(root).resolve()):
        raise ValueError('source changed since this run; status is stale')
    if state['state']=='preview_ready': verify_preview(run,state)
    result=dict(state)
    result['next_step']={'collecting':'Inspect interrupted collection; create a new run',
                         'blocked_collection':'Inspect candidates and diagnostics; explicit resume with --allow-partial is allowed only after a successful partial collection',
                         'awaiting_editorial_review':'Review sources and complete draft.json, then run preview',
                         'blocked_review':'Fix the reported editorial errors, then rerun preview',
                         'preview_ready':'Inspect the local preview; publication, scheduling and email still require separate setup/authority'}[state['state']]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare');prep.add_argument('--run-dir',type=Path,required=True)
    prep.add_argument('--date');prep.add_argument('--resume',action='store_true');prep.add_argument('--allow-partial',action='store_true')
    prep.add_argument('--sources',type=Path);prep.add_argument('--topic-config',type=Path)
    prep.add_argument('--general',action='store_true');prep.add_argument('--candidates',type=Path,help='Reuse a saved collection report without network calls')
    build=sub.add_parser('preview');build.add_argument('--run-dir',type=Path,required=True);build.add_argument('--reviewed-issue',type=Path)
    show=sub.add_parser('status');show.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.command=='prepare':
            if args.resume:
                if any((args.date,args.sources,args.topic_config,args.general,args.candidates)):
                    raise ValueError('--resume cannot replace existing inputs')
                result=prepare(args.run_dir,resume=True,allow_partial=args.allow_partial)
            else:
                if args.general and args.topic_config: raise ValueError('--general and --topic-config are mutually exclusive')
                topic=validate_topic() if args.general else load_topic(args.topic_config or ROOT/'daily/data/topics.json')
                result=prepare(args.run_dir,config=read_json(args.sources or ROOT/'daily/data/sources.json'),topic=topic,
                               issue_date=args.date,allow_partial=args.allow_partial,
                               candidate_report=read_json(args.candidates) if args.candidates else None)
        elif args.command=='preview': result=preview(args.run_dir,reviewed_file=args.reviewed_issue)
        else: result=status(args.run_dir)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['state'] in ('awaiting_editorial_review','preview_ready') else 2
    except (ValueError,KeyError,TypeError,OSError) as error:
        print('PIPELINE BLOCKED: '+str(error),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
