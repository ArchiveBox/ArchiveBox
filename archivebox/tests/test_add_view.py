import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from archivebox.config.common import SERVER_CONFIG, SEARCH_BACKEND_CONFIG
from archivebox.core.models import Tag
from archivebox.crawls.models import Crawl


pytestmark = pytest.mark.django_db

User = get_user_model()
WEB_HOST = 'web.archivebox.localhost:8000'
ADMIN_HOST = 'admin.archivebox.localhost:8000'


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username='addviewadmin',
        email='addviewadmin@test.com',
        password='testpassword',
    )


def test_add_view_renders_tag_editor_and_url_filter_fields(client, admin_user, monkeypatch):
    monkeypatch.setattr(SERVER_CONFIG, 'PUBLIC_ADD_VIEW', True)

    response = client.get(reverse('add'), HTTP_HOST=WEB_HOST)
    body = response.content.decode()

    assert response.status_code == 200
    assert 'tag-editor-container' in body
    assert 'name="url_filters_allowlist"' in body
    assert 'name="url_filters_denylist"' in body
    assert 'Same domain only' in body
    assert 'name="persona"' in body
    assert 'Overwrite existing snapshots' not in body
    assert 'Update/retry previously failed URLs' not in body
    assert 'Index only dry run (add crawl but don&#x27;t archive yet)' in body
    assert 'name="notes"' in body
    assert '<input type="text" name="notes"' in body
    assert body.index('name="persona"') < body.index('<h3>Crawl Plugins</h3>')
    assert 'data-url-regex=' in body
    assert 'id="url-highlight-layer"' in body
    assert 'id="detected-urls-list"' in body
    assert 'detected-url-toggle-btn' in body


def test_add_view_checks_configured_search_backend_by_default(client, monkeypatch):
    monkeypatch.setattr(SERVER_CONFIG, 'PUBLIC_ADD_VIEW', True)
    monkeypatch.setattr(SEARCH_BACKEND_CONFIG, 'SEARCH_BACKEND_ENGINE', 'sqlite')

    response = client.get(reverse('add'), HTTP_HOST=WEB_HOST)
    body = response.content.decode()

    assert response.status_code == 200
    assert re.search(
        r'<input type="checkbox" name="search_plugins" value="search_backend_sqlite"[^>]* checked\b',
        body,
    )
    assert "const requiredSearchPlugin = 'search_backend_sqlite';" in body


def test_add_view_creates_crawl_with_tag_and_url_filter_overrides(client, admin_user, monkeypatch):
    monkeypatch.setattr(SERVER_CONFIG, 'PUBLIC_ADD_VIEW', True)
    client.force_login(admin_user)

    response = client.post(
        reverse('add'),
        data={
            'url': 'https://example.com\nhttps://cdn.example.com/asset.js',
            'tag': 'alpha,beta',
            'depth': '1',
            'url_filters_allowlist': 'example.com\n*.example.com',
            'url_filters_denylist': 'cdn.example.com',
            'notes': 'Created from /add/',
            'schedule': '',
            'persona': 'Default',
            'index_only': '',
            'config': '{}',
        },
        HTTP_HOST=WEB_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by('-created_at').first()
    assert crawl is not None
    assert crawl.tags_str == 'alpha,beta'
    assert crawl.notes == 'Created from /add/'
    assert crawl.config.get('DEFAULT_PERSONA') == 'Default'
    assert crawl.config['URL_ALLOWLIST'] == 'example.com\n*.example.com'
    assert crawl.config['URL_DENYLIST'] == 'cdn.example.com'
    assert 'OVERWRITE' not in crawl.config
    assert 'ONLY_NEW' not in crawl.config


def test_add_view_extracts_urls_from_mixed_text_input(client, admin_user, monkeypatch):
    monkeypatch.setattr(SERVER_CONFIG, 'PUBLIC_ADD_VIEW', True)
    client.force_login(admin_user)

    response = client.post(
        reverse('add'),
        data={
            'url': '\n'.join([
                'https://sweeting.me,https://google.com',
                'Notes: [ArchiveBox](https://github.com/ArchiveBox/ArchiveBox), https://news.ycombinator.com',
                '[Wiki](https://en.wikipedia.org/wiki/Classification_(machine_learning))',
                '{"items":["https://example.com/three"]}',
                'csv,https://example.com/four',
            ]),
            'tag': '',
            'depth': '0',
            'url_filters_allowlist': '',
            'url_filters_denylist': '',
            'notes': '',
            'schedule': '',
            'persona': 'Default',
            'index_only': '',
            'config': '{}',
        },
        HTTP_HOST=WEB_HOST,
    )

    assert response.status_code == 302

    crawl = Crawl.objects.order_by('-created_at').first()
    assert crawl is not None
    assert crawl.urls == '\n'.join([
        'https://sweeting.me',
        'https://google.com',
        'https://github.com/ArchiveBox/ArchiveBox',
        'https://news.ycombinator.com',
        'https://en.wikipedia.org/wiki/Classification_(machine_learning)',
        'https://example.com/three',
        'https://example.com/four',
    ])


def test_add_view_exposes_api_token_for_tag_widget_autocomplete(client, admin_user, monkeypatch):
    monkeypatch.setattr(SERVER_CONFIG, 'PUBLIC_ADD_VIEW', True)
    client.force_login(admin_user)

    response = client.get(reverse('add'), HTTP_HOST=WEB_HOST)

    assert response.status_code == 200
    assert b'window.ARCHIVEBOX_API_KEY' in response.content


def test_tags_autocomplete_requires_auth_when_public_snapshots_list_disabled(client, settings):
    settings.PUBLIC_SNAPSHOTS_LIST = False
    settings.PUBLIC_INDEX = False
    Tag.objects.create(name='archive')

    response = client.get(
        reverse('api-1:tags_autocomplete'),
        {'q': 'a'},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 401


def test_tags_autocomplete_allows_public_access_when_public_snapshots_list_enabled(client, settings):
    settings.PUBLIC_SNAPSHOTS_LIST = True
    settings.PUBLIC_INDEX = False
    Tag.objects.create(name='archive')

    response = client.get(
        reverse('api-1:tags_autocomplete'),
        {'q': 'a'},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response.json()['tags'][0]['name'] == 'archive'


def test_tags_autocomplete_allows_authenticated_user_when_public_snapshots_list_disabled(client, admin_user, settings):
    settings.PUBLIC_SNAPSHOTS_LIST = False
    settings.PUBLIC_INDEX = False
    Tag.objects.create(name='archive')
    client.force_login(admin_user)

    response = client.get(
        reverse('api-1:tags_autocomplete'),
        {'q': 'a'},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response.json()['tags'][0]['name'] == 'archive'
