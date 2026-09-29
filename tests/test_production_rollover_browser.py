"""Run with: python -m pytest tests/test_production_rollover_browser.py"""
import threading
import os
from pathlib import Path
import pytest
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
from test_production_rollover import env


@pytest.fixture
def live(env):
    app, ids=env
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield f'http://127.0.0.1:{server.server_port}',ids
    server.shutdown();thread.join(timeout=5)


def local_cdn(context):
    # Optional exact-version upstream assets for environments that block browser CDN
    # requests. These are real Bootstrap/Socket.IO/Sortable assets, not test stubs.
    vendor = os.environ.get('COACHBOARD_TEST_VENDOR')
    if not vendor:
        return
    root = Path(vendor)
    mappings = {
      'https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/': root/'bootstrap-5.3.3/package/dist',
      'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/': root/'bootstrap-icons-1.11.3/package/font',
      'https://cdn.jsdelivr.net/npm/sortablejs@1.15.0/': root/'sortablejs-1.15.0/package',
      'https://cdn.socket.io/4.7.5/': root/'socket.io-client-4.7.5/package/dist',
    }
    for prefix, folder in mappings.items():
        def serve(route, request, *, prefix=prefix, folder=folder):
            path = folder/route.request.url.removeprefix(prefix).split('?')[0]
            route.fulfill(path=str(path))
        context.route(prefix+'**', serve)


@pytest.mark.parametrize('viewport',[{'width':1440,'height':1000},{'width':390,'height':844}])
def test_rollover_in_browser(live,viewport,tmp_path):
    url,ids=live
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--no-sandbox'])
        context=browser.new_context(viewport=viewport,ignore_https_errors=True)
        local_cdn(context)
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url+'/login')
        page.locator('[name=username]').fill('head');page.locator('[name=password]').fill('password')
        page.locator('button[type=submit]').click()
        expect(page.get_by_role('link',name='Teams & Seasons',exact=True)).to_be_visible()
        page.get_by_role('link',name='Teams & Seasons',exact=True).click()
        expect(page.get_by_role('heading',name='Teams & Seasons',exact=True)).to_be_visible()
        page.get_by_label('New team name (include the season)').fill('Prospects Spring 2027')
        page.get_by_label('Season',exact=True).fill('Spring 2027')
        page.locator(f'input[name=players][value="{ids["departing"]}"]').uncheck()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.locator('main').evaluate('(el) => el.scrollTop = 0')
        page.screenshot(path=str(tmp_path/f'rollover-{viewport["width"]}.png'),full_page=True)
        page.get_by_role('button',name='Create new team & switch').click()
        expect(page.get_by_text('New team created.',exact=False)).to_be_visible()
        expect(page.locator('h1')).to_have_text('Teams & Seasons')
        assert page.locator('input[name=players]').count()==1
        page.get_by_role('button',name='Open team',exact=True).click()
        expect(page.get_by_role('link',name='Teams & Seasons',exact=True)).to_be_visible()
        page.get_by_role('link',name='Teams & Seasons',exact=True).click()
        expect(page.locator('input[name=players]')).to_have_count(2)
        assert not errors, errors
        browser.close()


def test_archive_and_stale_tab_in_browser(live):
    url,ids=live
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--no-sandbox']);context=browser.new_context(ignore_https_errors=True)
        local_cdn(context)
        page=context.new_page();page.goto(url+'/login')
        page.locator('[name=username]').fill('head');page.locator('[name=password]').fill('password');page.locator('button[type=submit]').click()
        expect(page.get_by_role('link',name='Teams & Seasons',exact=True)).to_be_visible()
        # Actual production roster modal must submit the archive as a guarded POST.
        page.goto(url+'/#roster')
        page.locator('.player-card .card-header').first.click()
        page.get_by_role('button',name='Archive',exact=True).first.click()
        expect(page.get_by_role('heading',name='Archive player',exact=True)).to_be_visible()
        page.get_by_role('link',name='Archive player',exact=True).click()
        expect(page.get_by_text('archived. All history is preserved',exact=False)).to_be_visible()
        page.get_by_role('link',name='Teams & Seasons',exact=True).click()
        page.get_by_role('button',name='Restore player',exact=True).click()
        old_tab=context.new_page();old_tab.goto(url+'/')
        old_tab.on('dialog',lambda dialog:dialog.dismiss())
        page.get_by_label('New team name (include the season)').fill('Next season')
        page.get_by_label('Season',exact=True).fill('2027')
        page.get_by_role('button',name='Create new team & switch').click()
        expect(page.get_by_text('New team created.',exact=False)).to_be_visible()
        status=old_tab.evaluate("async () => (await fetch('/add_player',{method:'POST',body:new URLSearchParams({name:'Wrong team'})})).status")
        assert status==409
        browser.close()
