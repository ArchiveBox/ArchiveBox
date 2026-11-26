from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.mark.django_db
def test_activity_requires_admin_session(client, django_user_model, admin_user):
    path = "/admin/activity/"
    host = "admin.archivebox.localhost"
    assert client.get(path, HTTP_HOST=host).url.endswith("/admin/login/?next=/admin/activity/")

    user = django_user_model.objects.create_user(username="activity-viewer")
    client.force_login(user)
    assert client.get(path, HTTP_HOST=host).url.endswith("/admin/login/?next=/admin/activity/")

    client.force_login(admin_user)
    response = client.get(path, HTTP_HOST=host)
    assert response.status_code == 200
    assert b'name="csrfmiddlewaretoken"' in response.content
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.django_db(transaction=True)
def test_activity_expands_without_changing_desktop_preference(admin_user, live_server, browser_runtime):
    from archivebox.crawls.models import Crawl
    from archivebox.machine.models import Machine

    port = urlsplit(live_server.url).port
    origin = f"http://admin.archivebox.localhost:{port}"
    machine = Machine.current()
    machine.config = {**machine.config, "BASE_URL": f"http://archivebox.localhost:{port}"}
    machine.save(update_fields=["config"])
    crawl = Crawl.objects.create(urls="https://example.com/activity-control", created_by=admin_user)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_runtime["chrome_binary"]), args=browser_runtime["chrome_args"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{origin}/admin/login/?next=/admin/")
        page.locator("#id_username").fill(admin_user.username)
        page.locator("#id_password").fill("testpassword")
        page.locator('input[type="submit"]').click()
        page.wait_for_url("**/admin/")
        page.evaluate("localStorage.setItem('progress-monitor-collapsed', 'true')")

        with page.expect_response(
            lambda response: urlsplit(response.url).path == "/progress.json" and "tree=0" not in response.url,
        ) as progress:
            page.goto(f"{origin}/admin/activity/")
        assert progress.value.ok
        assert "active_crawls" in progress.value.json()
        expect(page.locator("#progress-monitor .progress-content")).to_be_visible()
        expect(page.locator("#progress-collapse")).to_be_hidden()
        assert page.locator("#header").count() == 0
        with page.expect_response(
            lambda response: response.request.method == "PATCH" and f"/api/v1/crawls/crawl/{crawl.pk}" in response.url,
        ) as paused:
            page.get_by_title("Pause crawl").click()
        assert paused.value.ok

        page.set_viewport_size({"width": 1200, "height": 800})
        page.goto(f"{origin}/admin/")
        expect(page.locator("#progress-collapse")).to_be_visible()
        expect(page.locator("#progress-collapse")).to_have_attribute("aria-expanded", "false")
        browser.close()

    crawl.refresh_from_db()
    assert crawl.is_paused
