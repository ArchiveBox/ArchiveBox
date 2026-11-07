"""Persona cookie policy reaches abx-dl's actual hook environment unchanged."""

import asyncio
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from archivebox.tests.conftest import ADMIN_TEST_HOST

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("strip_cookies", [False, True])
def test_persona_cookie_policy_admin_to_hook_environment(admin_client, admin_user, strip_cookies):
    from abx_dl.config import GlobalConfig, RuntimeConfig, get_plugin_env
    from archivebox.config.common import get_config
    from archivebox.core.models import Snapshot
    from archivebox.crawls.models import Crawl
    from archivebox.personas.models import Persona
    from archivebox.machine.models import Machine
    from archivebox.plugins.discovery import get_plugin_catalog
    from archivebox.services.runner import CrawlRunner

    key = "ARCHIVEWEBPAGE_STRIP_COOKIES"
    assert get_config()[key] is True
    # Exercise both explicit persona values against the opposite global value.
    machine = Machine.current()
    machine.config[key] = not strip_cookies
    machine.save(update_fields=["config"])
    assert get_config()[key] is not strip_cookies
    response = admin_client.get(reverse("admin:personas_persona_add"), HTTP_HOST=ADMIN_TEST_HOST)
    form = response.context["adminform"].form
    field = next(
        field for group in form.plugin_groups for plugin in group["plugins"] for field in plugin["config_fields"] if field["key"] == key
    )
    assert field["value"] == str(not strip_cookies).lower()
    response = admin_client.post(
        reverse("admin:personas_persona_add"),
        {
            "name": f"CookiePolicy{strip_cookies}",
            "created_by": str(admin_user.pk),
            "permissions": "private",
            "config": "{}",
            "import_mode": "none",
            f"plugin_config__archivewebpage__{key}": str(strip_cookies).lower(),
            "_save": "Save",
        },
        HTTP_HOST=ADMIN_TEST_HOST,
    )
    assert response.status_code == 302
    persona = Persona.objects.get(name=f"CookiePolicy{strip_cookies}")
    assert persona.config[key] is strip_cookies
    assert get_config(persona=persona)[key] is strip_cookies
    crawl = Crawl.objects.create(urls="https://example.com/cookie-policy", persona=persona, created_by=admin_user)
    snapshot = Snapshot.objects.create(url=crawl.urls, crawl=crawl)
    assert key not in crawl.config

    # Persona-owned plugin overrides remain live. Only an explicit crawl
    # override freezes that key; changing one persona cannot affect another.
    other = Persona.objects.create(name=f"OtherCookiePolicy{strip_cookies}", config={key: strip_cookies})
    explicit_crawl = Crawl.objects.create(
        urls="https://example.com/explicit-cookie-policy",
        persona=persona,
        created_by=admin_user,
        config={key: strip_cookies},
    )
    persona.config[key] = not strip_cookies
    persona.save(update_fields=["config"])
    assert get_config(persona=persona)[key] is not strip_cookies
    assert get_config(persona=other)[key] is strip_cookies
    assert get_config(crawl=crawl, snapshot=snapshot)[key] is not strip_cookies
    assert get_config(crawl=explicit_crawl)[key] is strip_cookies

    runner = CrawlRunner(crawl, show_progress=False)
    try:
        payload = async_to_sync(runner.load_snapshot_payload)(str(snapshot.id))
        assert payload["config"][key] is not strip_cookies
        runtime = RuntimeConfig(user=GlobalConfig(**payload["config"]), derived={})
        env = async_to_sync(get_plugin_env)(
            None,
            plugin=get_plugin_catalog()["archivewebpage"],
            run_output_dir=Path(payload["output_dir"]),
            config=runtime,
        ).to_env()
        assert env[key] == str(not strip_cookies)
        snapshot.config[key] = strip_cookies
        snapshot.save(update_fields=["config"])
        assert get_config(crawl=crawl, snapshot=snapshot)[key] is strip_cookies
    finally:
        asyncio.run(runner.bus.destroy(clear=False))
