import json
from datetime import datetime
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import UserManager
from django.urls import reverse
from django.utils import timezone


pytestmark = pytest.mark.django_db


User = get_user_model()
ADMIN_HOST = 'admin.archivebox.localhost:8000'


@pytest.fixture
def admin_user(db):
    return cast(UserManager, User.objects).create_superuser(
        username='tagadmin',
        email='tagadmin@test.com',
        password='testpassword',
    )


@pytest.fixture
def api_token(admin_user):
    from archivebox.api.auth import get_or_create_api_token

    token = get_or_create_api_token(admin_user)
    assert token is not None
    return token.token


@pytest.fixture
def crawl(admin_user):
    from archivebox.crawls.models import Crawl

    return Crawl.objects.create(
        urls='https://example.com',
        created_by=admin_user,
    )


@pytest.fixture
def tagged_data(crawl, admin_user):
    from archivebox.core.models import Snapshot, Tag

    tag = Tag.objects.create(name='Alpha Research', created_by=admin_user)
    first = Snapshot.objects.create(
        url='https://example.com/one',
        title='Example One',
        crawl=crawl,
    )
    second = Snapshot.objects.create(
        url='https://example.com/two',
        title='Example Two',
        crawl=crawl,
    )
    first.tags.add(tag)
    second.tags.add(tag)
    return tag, [first, second]


def test_tag_admin_changelist_renders_custom_ui(client, admin_user, tagged_data):
    client.login(username='tagadmin', password='testpassword')

    response = client.get(reverse('admin:core_tag_changelist'), HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 200
    assert b'id="tag-live-search"' in response.content
    assert b'id="tag-sort-select"' in response.content
    assert b'id="tag-created-by-select"' in response.content
    assert b'id="tag-year-select"' in response.content
    assert b'id="tag-has-snapshots-select"' in response.content
    assert b'Alpha Research' in response.content
    assert b'class="tag-card"' in response.content


def test_tag_admin_add_view_renders_similar_tag_reference(client, admin_user):
    client.login(username='tagadmin', password='testpassword')

    response = client.get(reverse('admin:core_tag_add'), HTTP_HOST=ADMIN_HOST)

    assert response.status_code == 200
    assert b'Similar Tags' in response.content
    assert b'data-tag-name-input="1"' in response.content


def test_tag_search_api_returns_card_payload(client, api_token, tagged_data):
    tag, snapshots = tagged_data

    response = client.get(
        reverse('api-1:search_tags'),
        {'q': 'Alpha', 'api_key': api_token},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['sort'] == 'created_desc'
    assert payload['created_by'] == ''
    assert payload['year'] == ''
    assert payload['has_snapshots'] == 'all'
    assert payload['tags'][0]['id'] == tag.id
    assert payload['tags'][0]['name'] == 'Alpha Research'
    assert payload['tags'][0]['num_snapshots'] == 2
    assert payload['tags'][0]['snapshots'][0]['title'] in {'Example One', 'Example Two'}
    assert payload['tags'][0]['export_jsonl_url'].endswith(f'/api/v1/core/tag/{tag.id}/snapshots.jsonl')
    assert payload['tags'][0]['filter_url'].endswith(f'/admin/core/snapshot/?tags__id__exact={tag.id}')
    assert {snapshot['url'] for snapshot in payload['tags'][0]['snapshots']} == {snap.url for snap in snapshots}


def test_tag_search_api_respects_sort_and_filters(client, api_token, admin_user, crawl, tagged_data):
    from archivebox.core.models import Snapshot, Tag

    other_user = cast(UserManager, User.objects).create_user(
        username='tagother',
        email='tagother@test.com',
        password='unused',
    )
    tag_with_snapshots = tagged_data[0]
    empty_tag = Tag.objects.create(name='Zulu Empty', created_by=other_user)
    alpha_tag = Tag.objects.create(name='Alpha Empty', created_by=other_user)
    Snapshot.objects.create(
        url='https://example.com/three',
        title='Example Three',
        crawl=crawl,
    ).tags.add(alpha_tag)

    Tag.objects.filter(pk=empty_tag.pk).update(created_at=timezone.make_aware(datetime(2024, 1, 1, 12, 0, 0)))
    Tag.objects.filter(pk=alpha_tag.pk).update(created_at=timezone.make_aware(datetime(2025, 1, 1, 12, 0, 0)))
    Tag.objects.filter(pk=tag_with_snapshots.pk).update(created_at=timezone.make_aware(datetime(2026, 1, 1, 12, 0, 0)))

    response = client.get(
        reverse('api-1:search_tags'),
        {
            'sort': 'name_desc',
            'created_by': str(other_user.pk),
            'year': '2024',
            'has_snapshots': 'no',
            'api_key': api_token,
        },
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['sort'] == 'name_desc'
    assert payload['created_by'] == str(other_user.pk)
    assert payload['year'] == '2024'
    assert payload['has_snapshots'] == 'no'
    assert [tag['name'] for tag in payload['tags']] == ['Zulu Empty']


def test_tag_rename_api_updates_slug(client, api_token, tagged_data):
    tag, _ = tagged_data

    response = client.post(
        f"{reverse('api-1:rename_tag', args=[tag.id])}?api_key={api_token}",
        data=json.dumps({'name': 'Alpha Archive'}),
        content_type='application/json',
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200

    tag.refresh_from_db()
    assert tag.name == 'Alpha Archive'
    assert tag.slug == 'alpha-archive'


def test_tag_snapshots_export_returns_jsonl(client, api_token, tagged_data):
    tag, _ = tagged_data

    response = client.get(
        reverse('api-1:tag_snapshots_export', args=[tag.id]),
        {'api_key': api_token},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response['Content-Type'].startswith('application/x-ndjson')
    assert f'tag-{tag.slug}-snapshots.jsonl' in response['Content-Disposition']
    body = response.content.decode()
    assert '"type": "Snapshot"' in body
    assert '"tags": "Alpha Research"' in body


def test_tag_urls_export_returns_plain_text_urls(client, api_token, tagged_data):
    tag, snapshots = tagged_data

    response = client.get(
        reverse('api-1:tag_urls_export', args=[tag.id]),
        {'api_key': api_token},
        HTTP_HOST=ADMIN_HOST,
    )

    assert response.status_code == 200
    assert response['Content-Type'].startswith('text/plain')
    assert f'tag-{tag.slug}-urls.txt' in response['Content-Disposition']
    exported_urls = set(filter(None, response.content.decode().splitlines()))
    assert exported_urls == {snapshot.url for snapshot in snapshots}
