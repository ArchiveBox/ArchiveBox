"""Check the built site in real Chromium at desktop and phone widths."""

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import expect, sync_playwright

HERE = Path(__file__).resolve().parent


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def verify(output, evidence):
    config = json.loads((HERE / "site.json").read_text())
    evidence.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(output.resolve())))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for name in config["pages"]:
                route = name.removesuffix("index.html")
                page = browser.new_page(reduced_motion="reduce")
                errors = []
                missing = []
                page.on("pageerror", lambda error, errors=errors: errors.append(str(error)))
                page.on(
                    "response",
                    lambda response, missing=missing: (
                        missing.append(response.url) if response.url.startswith(origin) and response.status >= 400 else None
                    ),
                )
                for width in [1440, 390]:
                    page.set_viewport_size({"width": width, "height": 900})
                    page.goto(f"{origin}/{route}", wait_until="domcontentloaded")
                    header = page.locator(".abx-header")
                    expect(header).to_have_count(1)
                    expect(header).to_have_css("display", "flex")
                    expect(page.locator(".abx-footer")).to_have_count(1)
                    expect(page.locator(".abx-footer-column")).to_have_count(3)
                    expect(header.locator(".abx-cta")).to_be_visible()
                    menu = header.locator(".abx-apps")
                    menu.locator("summary").focus()
                    page.keyboard.press("Enter")
                    expect(menu).to_have_attribute("open", "")
                    expect(menu.locator("a").first).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(menu).not_to_have_attribute("open", "")
                    menu.locator("summary").click()
                    box = header.bounding_box()
                    assert box
                    page.mouse.click(box["x"] + 2, box["y"] + 5)
                    expect(menu).not_to_have_attribute("open", "")
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"{name}: overflow at {width}"
                    # Decode every local content image using the real browser loader,
                    # including images in offscreen carousel tracks and lazy galleries.
                    images = page.locator("main img").evaluate_all("nodes => [...new Set(nodes.map(image => image.src))]")
                    local_images = [url for url in images if url.startswith(origin + "/")]
                    page.evaluate(
                        """async urls => {
                        for (const url of urls) {
                            const image = new Image();
                            image.src = url;
                            await image.decode();
                            if (!image.naturalWidth) throw new Error(`Broken image: ${url}`);
                        }
                    }""",
                        local_images,
                    )
                    page.evaluate("scrollTo({top: 0, behavior: 'instant'})")
                    page.screenshot(path=str(evidence / f"{route.replace('/', '-') or 'home-'}{width}.png"))
                    page.locator(".abx-footer").screenshot(path=str(evidence / f"{route.replace('/', '-') or 'home-'}footer-{width}.png"))
                    for link in header.locator(".abx-nav > a").all():
                        url = urlsplit(link.get_attribute("href") or "")
                        if url.scheme or url.netloc:
                            continue
                        response = page.request.get(urljoin(page.url, url.geturl()))
                        assert response.ok, f"Broken navigation: {url.geturl()}"
                        if url.fragment:
                            body = response.text()
                            assert f'id="{url.fragment}"' in body or f"id='{url.fragment}'" in body, (
                                f"Missing navigation anchor: {url.geturl()}"
                            )
                    if route == "" and page.locator("#resources").count():
                        page.goto(f"{origin}/#resources")
                        expect(page.locator("#resources")).to_be_visible()
                assert not errors, errors
                assert not missing, missing
                page.close()
                context = browser.new_context(java_script_enabled=False, viewport={"width": 390, "height": 900})
                plain = context.new_page()
                plain.goto(f"{origin}/{route}", wait_until="domcontentloaded")
                plain.locator(".abx-apps summary").click()
                expect(plain.locator(".abx-app-links a").first).to_be_visible()
                expect(plain.locator(".abx-footer-column a").first).to_be_visible()
                context.close()
                print(
                    f"PASS {name}: desktop/mobile, keyboard, no-JS, images and resources",
                    flush=True,
                )
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--evidence", type=Path, default=Path("test-results/site"))
    args = parser.parse_args()
    verify(args.output, args.evidence)
