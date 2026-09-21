"""Guardrail: one configured asset version, read by everyone.

The whole cache-busting mechanism rests on templates, server-injected script
tags and the browser-side loaders agreeing on a single string. They agree only
because all of them read ``app.config[asset_versioning.CONFIG_KEY]``.

The intended architecture is:

    ASSET_VERSION (or the process-start fallback) -> app.config -> everything

not a local variable captured by ``create_app()`` *alongside* the config value,
which is how it was first written -- two sources that happened to hold the same
string, and would have drifted the moment one of them was changed.

These tests prove the single path by mutating the config after the application
is built and showing every consumer follows. If someone reintroduces a captured
local, the mutation stops propagating and these fail.
"""

import pytest

from guardrail_support import build_app


@pytest.fixture(name='app')
def _app(monkeypatch):
    monkeypatch.setenv('ASSET_VERSION', 'configured-version')
    return build_app(monkeypatch)


def _rendered_template_version(app):
    """The value a template would see as ``asset_version``."""
    return app.jinja_env.from_string('{{ asset_version }}').render(
        **_template_context(app)
    )


def _template_context(app):
    context = {}
    for processor in app.template_context_processors[None]:
        context.update(processor())
    return context


def test_the_configured_version_is_what_create_app_established(app):
    from asset_versioning import CONFIG_KEY

    assert app.config[CONFIG_KEY] == 'configured-version'


def test_template_version_and_asset_url_agree(app):
    from asset_versioning import asset_url, current_asset_version

    with app.test_request_context('/'):
        template_version = _rendered_template_version(app)

        assert template_version == current_asset_version()
        assert asset_url('js/live_game_v2.js').endswith(f'?v={template_version}')


def test_both_consumers_follow_a_changed_config_value(app):
    """Mutate the config after app creation; everyone must observe it.

    This is the assertion that actually pins the architecture. A context
    processor that returned a local captured by ``create_app()`` would keep
    reporting the old string here while ``asset_url()`` reported the new one --
    exactly the silent divergence this guards against.
    """
    from asset_versioning import CONFIG_KEY, asset_url, current_asset_version

    with app.test_request_context('/'):
        assert _rendered_template_version(app) == 'configured-version'

        app.config[CONFIG_KEY] = 'changed-after-startup'

        assert current_asset_version() == 'changed-after-startup'
        assert _rendered_template_version(app) == 'changed-after-startup', (
            'the template-facing version did not follow app.config; something '
            'is holding its own copy of the asset version'
        )
        assert asset_url('js/live_game_v2.js').endswith('?v=changed-after-startup')


def test_the_year_timestamp_uses_the_same_source(app):
    """The home-link cache-buster is the same value by the same route."""
    from asset_versioning import CONFIG_KEY

    with app.test_request_context('/'):
        app.config[CONFIG_KEY] = 'changed-after-startup'
        context = _template_context(app)

        assert context['current_year_timestamp'] == 'changed-after-startup'


def test_asset_url_degrades_to_an_unversioned_url_without_a_version(app):
    """A missing version must not produce a broken tag."""
    from asset_versioning import CONFIG_KEY, asset_url

    with app.test_request_context('/'):
        app.config[CONFIG_KEY] = ''

        url = asset_url('js/live_game_v2.js')

        assert url.endswith('/static/js/live_game_v2.js')
        assert '?v=' not in url


def test_a_rendered_page_carries_the_configured_version(app):
    """End to end through a real template render, not just the processor."""
    from db import db

    with app.app_context():
        db.create_all()

    client = app.test_client()
    html = client.get('/login').get_data(as_text=True)

    assert 'content="configured-version"' in html, (
        'the page did not publish the configured asset version in its meta tag'
    )
    assert '?v=configured-version' in html
