from zlib import MAX_WBITS, decompressobj

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings as django_settings
from django.db import connection
from django.test import AsyncClient
from django.urls import reverse
from lxml import html

from archivebox.machine.models import Machine
from archivebox.personas.models import Persona
from archivebox.tests.conftest import ADMIN_TEST_HOST


def settings_grid(body):
    document = html.fromstring(body)
    return html.tostring(document.get_element_by_id("plugin-settings"), encoding="utf-8")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("page", ["add", "machine", "persona"])
def test_settings_streaming_preserves_the_complete_form(client, admin_user, page):
    persona = Persona.get_or_create_default()
    machine = Machine.current()
    path = {
        "add": "/add/",
        "machine": reverse("admin:machine_machine_change", args=[machine.pk]),
        "persona": reverse("admin:personas_persona_change", args=[persona.pk]),
    }[page]
    client.force_login(admin_user)
    buffered = client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
    assert buffered.status_code == 200
    assert not buffered.streaming

    browser = AsyncClient()
    browser.cookies.update(client.cookies)
    reading_body = False
    body_queries = []

    def record_query(execute, sql, params, many, context):
        if reading_body:
            body_queries.append(sql)
        return execute(sql, params, many, context)

    async def get_chunks():
        nonlocal reading_body
        response = await browser.request(
            method="GET",
            path=path,
            headers=[(b"host", ADMIN_TEST_HOST.encode()), (b"accept-encoding", b"gzip")],
        )
        assert response.status_code == 200
        assert response.streaming and response.is_async
        assert response["Content-Encoding"] == "gzip"
        assert "Accept-Encoding" in response["Vary"]
        assert {"private", "no-store"} <= set(response["Cache-Control"].split(", "))
        assert not response.has_header("Content-Length")
        assert response.cookies[django_settings.CSRF_COOKIE_NAME].value
        decoder = decompressobj(16 + MAX_WBITS)
        reading_body = True
        decoded = [decoder.decompress(chunk) async for chunk in response.streaming_content]
        assert decoder.eof
        return [part for part in decoded if part]

    with connection.execute_wrapper(record_query):
        chunks = async_to_sync(get_chunks)()
    assert body_queries == []
    assert b"</head>" in chunks[0]
    assert b'id="plugin-settings"' not in chunks[0]
    if page == "add":
        assert b'id="id_url"' in chunks[0]
    body = b"".join(chunks)
    assert settings_grid(body) == settings_grid(buffered.content)
    assert b"</html>" in body


@pytest.mark.django_db(transaction=True)
def test_settings_streaming_leaves_timing_custom_templates_and_validation_buffered(client, admin_user, settings):
    Persona.get_or_create_default()
    client.force_login(admin_user)
    browser = AsyncClient()
    browser.cookies.update(client.cookies)
    headers = [(b"host", ADMIN_TEST_HOST.encode())]
    request = async_to_sync(browser.request)

    timed = request(method="GET", path="/add/", headers=[*headers, (b"x-archivebox-admin-timing", b"1")])
    assert timed.status_code == 200 and not timed.streaming
    assert "admin_render;dur=" in timed["Server-Timing"]
    assert b'id="plugin-settings"' in timed.content

    head = request(method="HEAD", path="/add/", headers=[*headers])
    assert head.status_code == 200 and not head.streaming and not head.content

    invalid = request(method="POST", path="/add/", headers=[*headers])
    assert invalid.status_code == 200 and not invalid.streaming
    assert "url" in invalid.context_data["form"].errors

    settings.CUSTOM_TEMPLATES_ENABLED = True
    custom = request(method="GET", path="/add/", headers=[*headers])
    assert custom.status_code == 200 and not custom.streaming
    assert b'id="plugin-settings"' in custom.content


@pytest.mark.django_db(transaction=True)
def test_snapshot_stream_preserves_native_rows_selection_and_tag_editors(client, admin_user, crawl):
    from archivebox.core.models import Snapshot, Tag

    tag = Tag.objects.create(name="ArchiveBox release notes", created_by=admin_user)
    for i in range(50):
        snapshot = Snapshot.objects.create(
            crawl=crawl,
            url=f"https://github.com/ArchiveBox/ArchiveBox/issues/{i + 1}",
            status=Snapshot.StatusChoices.SEALED,
        )
        if i == 0:
            snapshot.tags.add(tag)
    path = reverse("admin:core_snapshot_changelist")
    client.force_login(admin_user)
    buffered = client.get(path, HTTP_HOST=ADMIN_TEST_HOST)
    assert buffered.status_code == 200 and not buffered.streaming
    browser = AsyncClient()
    browser.cookies.update(client.cookies)

    body_queries = []
    reading_body = False

    def record_query(execute, sql, params, many, context):
        if reading_body:
            body_queries.append(sql)
        return execute(sql, params, many, context)

    async def read():
        nonlocal reading_body
        response = await browser.request(method="GET", path=path, headers=[(b"host", ADMIN_TEST_HOST.encode())])
        assert response.status_code == 200 and response.streaming and response.is_async
        reading_body = True
        return [block async for block in response.streaming_content]

    with connection.execute_wrapper(record_query):
        chunks = async_to_sync(read)()
    assert not body_queries
    document = html.fromstring(b"".join(chunks))
    expected = html.fromstring(buffered.content)
    selector = '//table[@id="result_list"]/tbody/tr[@data-snapshot-id]'
    expected_rows = expected.xpath(selector)
    expected_ids = [r.attrib["data-snapshot-id"] for r in expected_rows]
    first_ids = [r.attrib["data-snapshot-id"] for r in html.fromstring(chunks[0]).xpath(selector)]
    assert len(expected_ids) == len(set(expected_ids)) == 50
    assert first_ids == expected_ids[:18]
    assert html.fromstring(chunks[0]).xpath('//template//span[@class="tag-pill"]')
    rows = document.xpath(selector)
    assert [r.attrib["data-snapshot-id"] for r in rows] == expected_ids
    assert [html.tostring(r, with_tail=False) for r in rows] == [html.tostring(r, with_tail=False) for r in expected_rows]
    assert len({r.xpath('.//input[@name="_selected_action"]/@value')[0] for r in rows}) == len(rows)
