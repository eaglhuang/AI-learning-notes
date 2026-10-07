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
    editions=[json.loads(path.read_text()) for path in sorted((ROOT/'daily/data/issues').glob('*.json'),reverse=True)]
    latest=editions[0];story_count=len(latest['items']);edition_count=len(editions)
    layout_contract=json.loads((ROOT/'tests/newsletter/fixtures/weekly-layouts.json').read_text())
    image_manifest=json.loads((ROOT/'daily/data/image-manifest.json').read_text())
    first_image=next(image for image in image_manifest['images'] if image['story_id']==latest['items'][0]['id'])
    category=latest['items'][0]['category'];category_count=sum(item['category']==category for item in latest['items'])
    report={'edition_date':latest['date'],'story_count':story_count,'edition_count':edition_count,'base_prefix_tested':base.endswith('/AI-learning-notes'),'checks':[],'screenshots':[]}
    def passed(name):report['checks'].append(name)
    def screenshot(page,name,full=True):
        page.screenshot(path=str(args.output/name),full_page=full);report['screenshots'].append(name)
    def position(page):return page.evaluate('({x:scrollX,y:scrollY,overflow:document.body.style.overflow})')
    def restored(page,before):
        after=position(page)
        assert abs(after['x']-before['x'])<=2 and abs(after['y']-before['y'])<=2,(before,after)
        assert after['overflow']==before['overflow'],(before,after)
    def no_overflow(page,label):
        if page.evaluate('document.documentElement.scrollWidth <= innerWidth'):return
        # Preserve the actual failing browser state; never mask overflow with clipping.
        name='overflow-'+str(label).replace(' ','').replace("'",'').replace('(','').replace(')','').replace(',','-')
        screenshot(page,name+'.png',False)
        diagnostic=page.evaluate('''() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,gridGap:getComputedStyle(document.querySelector('.headline-grid')).columnGap,overflow:[...document.querySelectorAll('.headline-grid,.headline-story,.headline-copy,.story-actions')].map(e=>({tag:e.tagName,id:e.id,className:e.className,x:e.getBoundingClientRect().x,width:e.getBoundingClientRect().width})).filter(e=>e.x<0||e.x+e.width>innerWidth)})''')
        (args.output/(name+'.json')).write_text(json.dumps(diagnostic,indent=2)+'\n')
        raise AssertionError(('horizontal overflow',label,diagnostic))
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':1440,'height':1000},reduced_motion='reduce')
            # All newsletter assets are local; block optional third-party resources
            # on the pre-existing homepage so the test has no tracking side effects.
            context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(base.split('/AI-learning-notes')[0]) else route.abort())
            page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(base+'/daily/');expect(page.locator('.headline-story:visible')).to_have_count(story_count)
            expect(page.locator('input[type=email]')).to_have_count(0)
            expect(page.locator('#result-count')).to_contain_text(str(story_count))
            screenshot(page,'desktop-zh.png');passed('desktop real issue, no email collection')
            page.locator(f'[data-filter="{category}"]').click();expect(page.locator('.headline-story:visible')).to_have_count(category_count)
            page.locator('#search').fill('zzzz-unmatchable');expect(page.locator('#empty-state')).to_be_visible()
            page.locator('#clear-filters').click();expect(page.locator('.headline-story:visible')).to_have_count(story_count);passed('category/search/empty-state/reset')
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
            expect(page.locator('#topic-settings-status')).to_contain_text('設定無效')
            page.locator('#topic-settings-form button[type=reset]').click()
            expect(page.locator('#topic-keywords')).to_have_value('')
            page.locator('#topic-settings summary').click()
            expect(page.locator('#topic-settings-form')).not_to_be_visible()
            expect(page.locator('.headline-story:visible')).to_have_count(story_count)
            passed('topic export, explicit aliases, invalid input, reset and close without changing issue')
            page.locator('#language').click();expect(page.locator('html')).to_have_attribute('lang','en')
            page.reload();expect(page.locator('html')).to_have_attribute('lang','en');passed('language preference persists through reload')
            page.locator('[data-summary-key]').first.click();expect(page.locator('#summary-dialog')).to_be_visible()
            expect(page.locator('[data-dialog-summary]')).to_have_text(latest['items'][0]['en']['summary'])
            screenshot(page,'desktop-en-summary.png');page.locator('[data-dialog-close]').click();passed('English full summary disclosure and close')
            for img in page.locator('.story-image img').all():
                img.scroll_into_view_if_needed()
                img.evaluate('(image)=>image.decode()')
            # Real browser coverage, not mocked DOM: 7 layouts × 2 locales × 4 widths.
            report['layout_scenarios']=[];report['summary_scenarios']=0;report['desktop_topology']={}
            ids=[i['id'] for i in latest['items']]
            for width in [1440,768,390,320]:
                page.set_viewport_size({'width':width,'height':1000})
                for locale in ['zh-TW','en']:
                    if page.locator('html').get_attribute('lang')!=locale:page.locator('#language').click()
                    for weekday in range(7):
                        page.locator('#weekday-layout').select_option(str(weekday))
                        expect(page.locator('.featured-story')).to_have_count(2)
                        expect(page.locator('.compact-story')).to_have_count(story_count-2)
                        assert page.locator('.headline-story').evaluate_all('(els)=>els.map(e=>e.id)')==ids
                        assert page.locator('.enhanced-issue').get_attribute('data-edition-date')==latest['date']
                        no_overflow(page,(width,locale,weekday))
                        assert page.locator('.story-image').evaluate_all('(els)=>els.every(e=>{const r=e.getBoundingClientRect();return r.width>0&&Math.abs(r.width/r.height-16/9)<0.08})')
                        assert page.locator('.story-image img').evaluate_all('(els)=>els.every(e=>e.complete&&e.naturalWidth>0)')
                        expect(page.locator('.summary-fallback').first).not_to_be_visible()
                        expect(page.locator('#summary-dialog')).not_to_be_visible()
                        assert page.locator('.headline-story h3 a').evaluate_all('(els)=>els.map(e=>e.href)')==[i['source_url'] for i in latest['items']]
                        for n,item in enumerate(latest['items']):
                            expect(page.locator('.story-image img').nth(n)).to_have_attribute('alt',page.locator('.story-image img').nth(n).get_attribute('data-alt-en' if locale=='en' else 'data-alt-zh'))
                        report['layout_scenarios'].append({'weekday':weekday,'locale':locale,'width':width,'passed':True})
                        if width==1440:
                            spans=page.locator('.headline-story').evaluate_all('(els)=>{const parent=els[0].parentElement,origin=parent.getBoundingClientRect(),style=getComputedStyle(parent),gap=parseFloat(style.columnGap),width=origin.width-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight),unit=(width-11*gap)/12;return els.map(e=>Math.round((e.getBoundingClientRect().width+gap)/(unit+gap))) }')
                            contract=layout_contract[weekday]
                            expected=contract['featured_columns']+[contract['brief_columns']]*(story_count-2)
                            expected[-1]=contract['last_brief_columns']
                            assert spans==expected,('column topology',weekday,locale,spans,expected)
                            report['desktop_topology'].setdefault(locale,[]).append(spans)
                            screenshot(page,f'layout-{weekday}-{locale}.png')
                            for n,item in enumerate(latest['items']):
                                trigger=page.locator('[data-summary-key]').nth(n);trigger.scroll_into_view_if_needed()
                                before=position(page)
                                trigger.click();expect(page.locator('#summary-dialog')).to_be_visible()
                                assert page.evaluate('document.body.style.overflow')=='hidden'
                                expect(page.locator('[data-dialog-summary]')).to_have_text(item[locale]['summary'])
                                expect(page.locator('[data-dialog-takeaway]')).to_have_text(item[locale]['takeaway'])
                                expect(page.locator('[data-dialog-caveat]')).to_have_text(item[locale]['caveat'])
                                page.locator('[data-dialog-close]').click();expect(page.locator('#summary-dialog')).not_to_be_visible()
                                expect(trigger).to_be_focused();restored(page,before);report['summary_scenarios']+=1
            assert len(report['layout_scenarios'])==56 and report['summary_scenarios']==7*2*story_count
            for locale,topologies in report['desktop_topology'].items():
                assert len({tuple(value) for value in topologies})==7,('layouts must have seven distinct column topologies',locale)
            passed(f'56 real layout/language/viewport scenarios and {report["summary_scenarios"]} complete summary open-close operations')
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('[data-summary-key]').first.click()
            old_locale=page.locator('html').get_attribute('lang');next_locale='zh-TW' if old_locale=='en' else 'en'
            page.locator('[data-dialog-language]').click();expect(page.locator('html')).to_have_attribute('lang',next_locale)
            expect(page.locator('[data-dialog-summary]')).to_have_text(latest['items'][0][next_locale]['summary'])
            page.locator('#dialog-layout').select_option('3');expect(page.locator('.enhanced-issue')).to_have_attribute('data-weekday','3')
            expect(page.locator('#summary-dialog')).to_be_visible()
            page.locator('[data-dialog-language]').focus();page.keyboard.press('Shift+Tab');expect(page.locator('[data-dialog-source]')).to_be_focused()
            page.keyboard.press('Tab');expect(page.locator('[data-dialog-language]')).to_be_focused()
            page.keyboard.press('Escape');expect(page.locator('#summary-dialog')).not_to_be_visible()
            # Capture after the changed layout has settled, then test both alternate dismissal routes.
            page.locator('[data-summary-key]').first.scroll_into_view_if_needed();before=position(page)
            page.locator('[data-summary-key]').first.click();page.keyboard.press('Escape');restored(page,before)
            page.locator('[data-summary-key]').nth(1).scroll_into_view_if_needed();before=position(page)
            page.locator('[data-summary-key]').nth(1).click();expect(page.locator('[data-dialog-summary]')).to_have_text(latest['items'][1][next_locale]['summary'])
            page.mouse.click(2,2);expect(page.locator('#summary-dialog')).not_to_be_visible();restored(page,before)
            if page.locator('html').get_attribute('lang')!='en':page.locator('#language').click()
            passed('open-dialog language/layout change, focus loop, Escape, backdrop and another story')
            page.locator('header nav').get_by_role('link',name='Archive',exact=True).click();expect(page.locator('.archive-card:visible')).to_have_count(edition_count)
            page.locator('#archive-date').fill('2026-10-03');expect(page.locator('#empty-state')).to_be_visible()
            page.locator('#clear-filters').click();expect(page.locator('.archive-card:visible')).to_have_count(edition_count)
            page.locator('#search').fill(latest['title']['en']);expect(page.locator('.archive-card:visible')).to_have_count(1)
            page.locator('#search').fill('does not exist');expect(page.locator('#empty-state')).to_be_visible()
            page.locator('#clear-filters').click();screenshot(page,'archive-en.png');passed('archive date/search/reset')
            expect(page.locator('#history-query')).to_be_visible()
            for day in ['2026-10-04','2026-10-06']:
                historical=next(i for i in editions if i['date']==day)['items'][0]
                page.locator('#history-query').fill(historical['en']['title'])
                expect(page.locator('.archive-search-result')).to_have_count(1)
                expect(page.locator('.archive-search-result')).to_contain_text(day)
                page.locator('.archive-search-result button').first.click()
                expect(page.locator('[data-dialog-summary]')).to_have_text(historical['en']['summary'])
                page.locator('[data-dialog-language]').click()
                expect(page.locator('[data-dialog-summary]')).to_have_text(historical['zh-TW']['summary'])
                page.locator('[data-dialog-close]').click();expect(page.locator('#history-query')).to_be_focused()
                expect(page.locator('#history-query')).to_have_value(historical['en']['title'])
                page.locator('#language').click()
            page.locator('#history-query').fill('no-such-archive-result-271828');expect(page.locator('#all-history-search')).to_contain_text('No matches')
            page.locator('#all-history-search').get_by_role('button',name='Reset',exact=True).click()
            expect(page.locator('.archive-search-result')).to_have_count(sum(len(i['items']) for i in editions))
            page.locator('#archive-date').fill('2026-10-03');expect(page.locator('.archive-search-result')).to_have_count(sum(len(i['items']) for i in editions))
            page.locator('#clear-filters').click();passed('all-history content search, older editions, independent date filter, modal locale and query/reset')
            page.go_back();expect(page.locator('html')).to_have_attribute('lang','en');page.go_forward();expect(page.locator('.archive-card')).to_have_count(edition_count);passed('back/forward navigation')
            page.goto(base+'/');expect(page.locator('#atomic-daily')).to_be_visible();expect(page.locator('#articles')).to_have_count(1)
            page.locator('#atomic-daily').screenshot(path=str(args.output/'homepage-zone.png'));report['screenshots'].append('homepage-zone.png');passed('homepage independent newsletter zone and preserved articles')
            for width in [390,320]:
                mobile=browser.new_context(viewport={'width':width,'height':844},is_mobile=True,has_touch=True,reduced_motion='reduce')
                mp=mobile.new_page();mp.goto(base+'/daily/')
                expect(mp.locator('.headline-story:visible')).to_have_count(story_count)
                assert mp.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),f'{width}px overflow'
                mp.locator('#language').click();expect(mp.locator('html')).to_have_attribute('lang','en')
                assert mp.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),f'{width}px English overflow'
                if width==390:screenshot(mp,'mobile-en.png')
                passed(f'{width}px mobile both languages without overflow');mobile.close()
            nojs=browser.new_context(java_script_enabled=False,viewport={'width':1280,'height':900})
            np=nojs.new_page();np.goto(base+'/daily/en/');expect(np.locator('html')).to_have_attribute('lang','en')
            np.locator('header nav').get_by_role('link',name='Archive',exact=True).click();expect(np.locator('html')).to_have_attribute('lang','en')
            np.get_by_role('link',name='Read the issue').first.click();expect(np.locator('html')).to_have_attribute('lang','en')
            expect(np.locator('.headline-story')).to_have_count(story_count);expect(np.locator('#issue-date')).not_to_be_visible()
            np.locator('.summary-fallback summary').first.click();expect(np.locator('.summary-fallback').first).to_contain_text(latest['items'][0]['en']['summary'])
            for locale,path in [('zh-TW','/daily/'),('en','/daily/en/')]:
                np.goto(base+path);expect(np.locator('html')).to_have_attribute('lang',locale)
                expect(np.locator('.summary-fallback').first).not_to_have_attribute('open','')
                np.locator('.summary-fallback summary').first.click();expect(np.locator('.summary-fallback').first).to_contain_text(latest['items'][0][locale]['summary'])
            passed('no-JavaScript bilingual closed disclosures and English navigation')
            for filename in ['wide.svg','portrait.svg','large-dimensions.svg','broken.jpg']:
                fixture_context=browser.new_context(viewport={'width':320,'height':844})
                fp=fixture_context.new_page()
                fp.route('**/'+first_image['path'],lambda route,f=filename:route.fulfill(path=str(ROOT/'tests/newsletter/fixtures/images'/f),content_type='image/svg+xml' if f.endswith('.svg') else 'image/jpeg'))
                fp.goto(base+'/daily/')
                image=fp.locator('.story-image').first
                if filename=='broken.jpg':expect(image.locator('.image-fallback')).to_be_visible();expect(image.locator('img')).not_to_be_visible()
                else:expect(image.locator('img')).to_be_visible()
                assert image.evaluate('(e)=>{const r=e.getBoundingClientRect();return Math.abs(r.width/r.height-16/9)<0.08}')
                assert fp.evaluate('document.documentElement.scrollWidth <= innerWidth')
                fixture_context.close()
            passed('wide/portrait/extreme intrinsic dimensions and corrupt-image fixed-frame fallback')
            blocked=browser.new_context();blocked.add_init_script("Object.defineProperty(window, 'localStorage', {get(){throw new DOMException('Disabled','SecurityError')}})")
            bp=blocked.new_page();bp.goto(base+'/daily/');bp.locator('#language').click();expect(bp.locator('html')).to_have_attribute('lang','en')
            expect(bp.locator('#topic-match option[value=any]')).to_have_text('OR / Any keyword')
            expect(bp.locator('#topic-settings-status')).to_have_text('Local configuration preview only')
            # Keep local links on the test origin while preserving their actual path/query/hash.
            permanent=bp.locator('.headline-story .permalink').first.get_attribute('href')
            from urllib.parse import urlsplit
            parsed=urlsplit(permanent);assert 'lang=en' in parsed.query
            bp.goto(base.split('/AI-learning-notes')[0]+parsed.path+'?'+parsed.query+'#'+parsed.fragment)
            expect(bp.locator('html')).to_have_attribute('lang','en');expect(bp.locator('.headline-story').first).to_have_attribute('id',latest['items'][0]['id'])
            passed('blocked-storage language toggle and permanent-link navigation')
            archive_index=json.loads((ROOT/'daily/data/search-index.json').read_text())
            invalid=json.loads(json.dumps(archive_index));invalid['records'][0]['sourceUrl']='javascript:alert(1)'
            for failure in ['abort','malformed','oversized','unsafe-index']:
                failure_context=browser.new_context();failed_page=failure_context.new_page()
                def fail_index(route,case=failure):
                    if case=='abort':route.abort();return
                    body={'malformed':'{broken','oversized':'x'*4000001,'unsafe-index':json.dumps(invalid)}[case]
                    route.fulfill(status=200,content_type='application/json',body=body)
                failed_page.route('**/data/search-index.json',fail_index)
                failed_page.goto(base+'/daily/archive/')
                expect(failed_page.locator('#all-history-search [role=status]')).to_contain_text('暫時無法載入')
                expect(failed_page.locator('.archive-card')).to_have_count(edition_count)
                expect(failed_page.locator('.archive-search-result')).to_have_count(0)
                expect(failed_page.locator('#all-history-search img')).to_have_count(0)
                assert not failed_page.locator('a[href^="javascript:"]').count()
                failed_page.locator('#language').click()
                expect(failed_page.locator('#all-history-search [role=status]')).to_contain_text('could not load')
                failed_page.locator('.archive-card').first.get_by_role('link',name='Read the issue').click()
                expect(failed_page.locator('.headline-story')).to_have_count(story_count)
                failure_context.close()
            passed('archive network/malformed/oversized/unsafe-index failures keep localized fallback and working edition links')
            assert not errors,errors;passed('no newsletter runtime errors')
            browser.close()
    finally:
        if server:server.shutdown()
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
