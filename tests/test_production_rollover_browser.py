"""Run with: python -m pytest tests/test_production_rollover_browser.py"""
import threading
import os
from pathlib import Path
import pytest
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect
from test_production_rollover import env
from db import db
from models import Player, Rotation


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
        page.get_by_label('Team name',exact=True).fill('Prospects Spring 2027')
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
        page.get_by_label('Team name',exact=True).fill('Next season')
        page.get_by_label('Season',exact=True).fill('2027')
        page.get_by_role('button',name='Create new team & switch').click()
        expect(page.get_by_text('New team created.',exact=False)).to_be_visible()
        status=old_tab.evaluate("async () => (await fetch('/add_player',{method:'POST',body:new URLSearchParams({name:'Wrong team'})})).status")
        assert status==409
        browser.close()


@pytest.mark.parametrize('viewport',[{'width':1440,'height':900},{'width':390,'height':844}])
def test_create_defense_template_without_a_game(live,env,viewport):
    url,ids=live
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--no-sandbox'])
        context=browser.new_context(viewport=viewport)
        local_cdn(context)
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url+'/login')
        page.locator('[name=username]').fill('head');page.locator('[name=password]').fill('password')
        page.locator('button[type=submit]').click()
        page.goto(url+'/#rotations')
        page.get_by_role('button',name='Create New').click(timeout=5000)
        page.get_by_label('Template name').fill('Starting defense')
        page.get_by_label('1B',exact=True).select_option(label='Graham')
        page.get_by_label('2B',exact=True).select_option(label='Graham')
        expect(page.get_by_text('Graham is already on the field this inning.')).to_be_visible()
        page.get_by_label('2B',exact=True).select_option(label='Departing')
        page.get_by_role('button',name='Add inning').click()
        page.get_by_role('button',name='Copy previous').click()
        page.get_by_role('button',name='Save Template').click()
        expect(page.get_by_text('Starting defense',exact=True)).to_be_visible()
        with env[0].app_context():
            saved=Rotation.query.filter_by(team_id=ids['old'],title='Starting defense').one()
            assert saved.associated_game_id is None
            assert saved.innings=={'1':{'1B':'Graham','2B':'Departing'},
                                   '2':{'1B':'Graham','2B':'Departing'}}
        assert not errors,errors
        browser.close()


def test_dragging_over_occupied_position_keeps_player_until_drop(live,env):
    url,ids=live
    with env[0].app_context():
        db.session.add(Player(team_id=ids['old'],name='Bench Player'))
        db.session.commit()
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1000})
        local_cdn(context)
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url+'/login')
        page.locator('[name=username]').fill('head');page.locator('[name=password]').fill('password')
        page.locator('button[type=submit]').click()
        page.goto(url+f'/game/{ids["game"]}')
        old=page.locator('#pos-desktop-P .player-tag[data-player-name="Graham"]')
        source=page.locator('#bench-list-desktop .player-tag[data-player-name="Bench Player"]')
        expect(old).to_have_count(1)
        start=source.bounding_box(); occupied=page.locator('#pos-desktop-P').bounding_box()
        empty=page.locator('#pos-desktop-CF').bounding_box()
        page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
        page.mouse.down()
        page.mouse.move(occupied['x']+occupied['width']/2,occupied['y']+occupied['height']/2,steps=12)
        expect(old).to_have_count(1)
        with env[0].app_context():
            assert Rotation.query.filter_by(team_id=ids['old'],associated_game_id=ids['game']).one().innings['1']['P']=='Graham'
        page.mouse.move(empty['x']+empty['width']/2,empty['y']+empty['height']/2,steps=12)
        page.mouse.up()
        expect(old).to_have_count(1)
        cf_player=page.locator('#pos-desktop-CF .player-tag[data-player-name="Bench Player"]')
        expect(cf_player).to_have_count(1)
        start=cf_player.bounding_box()
        page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
        page.mouse.down()
        page.mouse.move(occupied['x']+occupied['width']/2,occupied['y']+occupied['height']/2,steps=12)
        page.mouse.move(1080,500,steps=12)
        page.mouse.up()
        expect(old).to_have_count(1)
        expect(cf_player).to_have_count(1)
        start=cf_player.bounding_box()
        page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
        page.mouse.down()
        page.mouse.move(occupied['x']+occupied['width']/2,occupied['y']+occupied['height']/2,steps=12)
        page.mouse.up()
        expect(page.locator('#pos-desktop-P .player-tag[data-player-name="Bench Player"]')).to_have_count(1)
        expect(page.locator('#bench-list-desktop .player-tag[data-player-name="Graham"]')).to_have_count(1)
        assert not errors,errors
        browser.close()


def test_touch_drag_cannot_synthesize_a_remove_tap(live,env):
    url,ids=live
    with env[0].app_context():
        db.session.add(Player(team_id=ids['old'],name='Bench Player'))
        db.session.commit()
    with sync_playwright() as p:
        browser=p.chromium.launch(args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1376,'height':1032},has_touch=True)
        local_cdn(context)
        page=context.new_page();page.goto(url+'/login')
        page.locator('[name=username]').fill('head');page.locator('[name=password]').fill('password')
        page.locator('button[type=submit]').click()
        page.goto(url+f'/game/{ids["game"]}')
        expect(page.locator('#touch-defense-instructions')).to_be_visible()
        old=page.locator('#pos-desktop-P .player-tag[data-player-name="Graham"]')
        expect(old).to_have_count(1)
        bench=page.locator('#bench-list-desktop .player-tag[data-player-name="Bench Player"]')
        start=bench.bounding_box();occupied=page.locator('#pos-desktop-P').bounding_box()
        page.mouse.move(start['x']+start['width']/2,start['y']+start['height']/2)
        page.mouse.down()
        page.mouse.move(occupied['x']+occupied['width']/2,occupied['y']+occupied['height']/2,steps=12)
        page.mouse.up()
        expect(old).to_have_count(1)
        # A touch browser may deliver its synthetic click after pointerup.
        page.locator('#pos-desktop-P').dispatch_event('click')
        expect(old).to_have_count(1)
        page.locator('#pos-desktop-P').click()
        expect(old).to_have_count(0)
        browser.close()
