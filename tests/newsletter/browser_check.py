#!/usr/bin/env python3
"""Portable CI browser regression and screenshot suite (requires Playwright).

This tests repository fixtures only. It never signs up an address or sends mail.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[2]


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self,path):
        prefix='/AI-learning-notes/'
        if path.startswith(prefix):path='/'+path[len(prefix):]
        return super().translate_path(path)
    def log_message(self,*args):pass


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    server=None
    if args.base:base=args.base.rstrip('/')
    else:
        server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}/AI-learning-notes'
    report={'base_prefix_tested':base.endswith('/AI-learning-notes'),'checks':[],'screenshots':[]}
    def passed(name):report['checks'].append(name)
    def screenshot(page,name,full=True):
        page.screenshot(path=str(args.output/name),full_page=full);report['screenshots'].append(name)
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            # All newsletter assets are local; block optional third-party resources
            # on the pre-existing homepage so the test has no tracking side effects.
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base.split('/AI-learning-notes')[0]) else route.abort())
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/daily/');expect(page.locator('.story:visible')).to_have_count(10)
            expect(page.locator('input[type=email]')).to_have_count(0)
            expect(page.locator('#result-count')).to_contain_text('10')
            screenshot(page,'desktop-zh.png');passed('desktop real issue, no email collection')
            page.get_by_role('button',name='論文',exact=True).click();expect(page.locator('.story:visible')).to_have_count(2)
            page.locator('#search').fill('zzzz-unmatchable');expect(page.locator('#empty-state')).to_be_visible()
            page.locator('#clear-filters').click();expect(page.locator('.story:visible')).to_have_count(10);passed('category/search/empty-state/reset')
            # Topic settings are local configuration only, never a server save/search.
            page.locator('#topic-settings summary').click()
            page.locator('#topic-keywords').fill('具身智能\nrobotics')
            page.locator('#topic-aliases').fill('具身智能=embodied AI|embodied intelligence')
            page.locator('#topic-match').select_option('all')
            expect(page.locator('#topic-config-preview')).to_contain_text('embodied AI')
            with page.expect_download() as download:
                page.locator('#topic-settings-form button[type=submit]').click()
            exported=download.value;assert exported.suggested_filename=='topics.json'
            exported.save_as(args.output/'exported-topics.json')
            config=json.loads((args.output/'exported-topics.json').read_text())
            assert config['keywords']==['具身智能','robotics'] and config['match']=='all'
            page.locator('#topic-keywords').fill('</textarea><script>alert(1)</script>')
            expect(page.locator('#topic-config-preview')).to_have_text('')
            expect(page.locator('#topic-settings-status')).to_contain_text('literal')
            page.locator('#topic-settings-form button[type=reset]').click()
            expect(page.locator('#topic-keywords')).to_have_value('')
            page.locator('#topic-settings summary').click()
            expect(page.locator('#topic-settings-form')).not_to_be_visible()
            expect(page.locator('.story:visible')).to_have_count(10)
            passed('topic export, explicit aliases, invalid input, reset and close without changing issue')
            page.locator('#language').click();expect(page.locator('html')).to_have_attribute('lang','en')
            page.reload();expect(page.locator('html')).to_have_attribute('lang','en');passed('language preference persists through reload')
            page.locator('.caveat summary').first.click();expect(page.locator('.caveat').first).to_have_attribute('open','')
            screenshot(page,'desktop-en.png');passed('English details disclosure')
            page.locator('header nav').get_by_role('link',name='Archive',exact=True).click();expect(page.locator('.archive-card:visible')).to_have_count(1)
            page.locator('#archive-date').fill('2026-10-03');expect(page.locator('#empty-state')).to_be_visible()
            page.locator('#clear-filters').click();expect(page.locator('.archive-card:visible')).to_have_count(1)
            page.locator('#search').fill('Prime');expect(page.locator('.archive-card:visible')).to_have_count(1)
            page.locator('#search').fill('does not exist');expect(page.locator('#empty-state')).to_be_visible()
            page.locator('#clear-filters').click();screenshot(page,'archive-en.png');passed('archive date/search/reset')
            page.go_back();expect(page.locator('html')).to_have_attribute('lang','en');page.go_forward();expect(page.locator('.archive-card')).to_have_count(1);passed('back/forward navigation')
            page.goto(base+'/');expect(page.locator('#atomic-daily')).to_be_visible();expect(page.locator('#articles')).to_have_count(1)
            page.locator('#atomic-daily').screenshot(path=str(args.output/'homepage-zone.png'));report['screenshots'].append('homepage-zone.png');passed('homepage independent newsletter zone and preserved articles')
            for width in [390,320]:
                mobile=browser.new_context(viewport={'width':width,'height':844},is_mobile=True,has_touch=True,reduced_motion='reduce')
                mp=mobile.new_page();mp.goto(base+'/daily/')
                expect(mp.locator('.story:visible')).to_have_count(10)
                assert mp.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),f'{width}px overflow'
                mp.locator('#language').click();expect(mp.locator('html')).to_have_attribute('lang','en')
                assert mp.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),f'{width}px English overflow'
                if width==390:screenshot(mp,'mobile-en.png')
                passed(f'{width}px mobile both languages without overflow');mobile.close()
            nojs=browser.new_context(java_script_enabled=False,viewport={'width':1280,'height':900})
            np=nojs.new_page();np.goto(base+'/daily/en/');expect(np.locator('html')).to_have_attribute('lang','en')
            np.locator('header nav').get_by_role('link',name='Archive',exact=True).click();expect(np.locator('html')).to_have_attribute('lang','en')
            np.get_by_role('link',name='Read the issue').click();expect(np.locator('html')).to_have_attribute('lang','en')
            expect(np.locator('.story')).to_have_count(10);expect(np.locator('#issue-date')).not_to_be_visible();passed('no-JavaScript complete English navigation')
            blocked=browser.new_context();blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get(){throw new DOMException('Disabled','SecurityError')}})")
            bp=blocked.new_page();bp.goto(base+'/daily/');bp.locator('#language').click();expect(bp.locator('html')).to_have_attribute('lang','en');passed('blocked storage language fallback')
            assert not errors,errors;passed('no newsletter runtime errors')
            browser.close()
    finally:
        if server:server.shutdown()
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
