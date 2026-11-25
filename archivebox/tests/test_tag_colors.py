import re

import pytest
from playwright.sync_api import expect, sync_playwright

from archivebox.core.models import Snapshot, Tag
from archivebox.core.tag_colors import tag_color_style
from archivebox.machine.models import Machine


def _hue(name):
    return int(re.search(r"hsl\((\d+)", tag_color_style(name)).group(1))


def _current_hash(name):
    hue = 0
    for char in name.strip().lower():
        hue = (hue * 31 + ord(char)) % 360
    return hue


def test_related_tag_colors_and_unknown_fallback():
    for a, b in (("pastry", "dessert"), ("guitarist", "violin"), ("mortgage", "loan"), ("ocean", "sailing")):
        assert min((_hue(a) - _hue(b)) % 360, (_hue(b) - _hue(a)) % 360) <= 16
    assert _hue("  VIOLIN ") == _hue("violin")
    assert min((_hue("guitarist violin") - _hue("violin")) % 360, (_hue("violin") - _hue("guitarist violin")) % 360) <= 16
    for name in ("physics", "gamma-rays", "quantum physics"):
        assert 212 <= _hue(name) <= 228
    for family, child in (("archivebox", "archivebox-wiki"), ("foobarbaz", "FOOBARBAZ_WIKIWIKI"), ("spurklet", "spurklet:flibbles")):
        assert min((_hue(family) - _hue(child)) % 360, (_hue(child) - _hue(family)) % 360) <= 8
    for name in ("⭐", "2026", "xyz:7bca-🧪"):
        assert _hue(name) == _current_hash(name)


@pytest.mark.django_db(transaction=True)
def test_browser_keeps_the_rendered_tag_colors(live_server, admin_user, browser_runtime, crawl):
    machine = Machine.current()
    machine.config.update(BASE_URL=live_server.url, SERVER_SECURITY_MODE="safe-onedomain-nojsreplay")
    machine.save(update_fields=["config"])
    snapshot = Snapshot.objects.create(url="https://www.example.com/features", title="Saved tag colors", crawl=crawl, status="sealed")
    names = ("archivebox", "archivebox-wiki", "physics", "gamma-rays", "⭐")
    snapshot.tags.set([Tag.objects.create(name=name) for name in names])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.goto(live_server.url + "/admin/login/?next=/admin/core/snapshot/")
        page.get_by_label("Username:", exact=True).fill(admin_user.username)
        page.get_by_label("Password:", exact=True).fill("testpassword")
        page.get_by_role("button", name="Log in", exact=True).click()
        row = page.locator(f'tr[data-snapshot-id="{snapshot.pk}"]')
        expect(row).to_be_visible()
        for name in (*names, " \u001cVIOLIN ", "🧪 xyz:7bca", "guitarist / mortgage", "café", "Ocean sailing"):
            expected = dict(part.strip().split(": ", 1) for part in tag_color_style(name).strip(";").split(";"))
            assert (
                page.evaluate(
                    """name => {
                    const badge = document.createElement('span');
                    window.applyArchiveBoxTagColor(badge, name);
                    return Object.fromEntries([...badge.style].map(prop => [prop, badge.style.getPropertyValue(prop)]));
                }""",
                    name,
                )
                == expected
            )
        for name in names:
            badge = row.locator(f'.tag-pill[data-tag="{name}"]')
            assert badge.evaluate("badge => badge.style.getPropertyValue('--tag-bg')") in tag_color_style(name)
        browser.close()
