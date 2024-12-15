#!/usr/bin/env node

import {puppeteer} from 'puppeteer'
import {exec} from 'node:child_process'

// # CHROME_BINARY="${CHROME_BINARY:-"$(./binaries.py | awk '{print $2}')"}"

// # mapfile -t CHROME_ARGS < <(./config.py CHROME_ARGS)
// # IFS=' '
// # echo "cmd:            ${CHROME_BINARY}" "${CHROME_ARGS[@]}" "--screenshot=screenshot.png" "$1"


// # # exec grep -m 1 "bytes written to file" <("$CHROME_BINARY" "${CHROME_ARGS[@]}" --screenshot "$1" 2>&1)
// # eval "$CHROME_BINARY ${CHROME_ARGS[*]} --screenshot=screenshot.png $1"


// # # cmd:            /Volumes/NVME/Users/squash/Library/Caches/ms-playwright/chromium-1112/chrome-mac/Chromium.app/Contents/MacOS/Chromium --disable-sync --no-pings --no-first-run --no-default-browser-check --disable-default-apps --ash-no-nudges --disable-infobars --disable-blink-features=AutomationControlled --js-flags=--random-seed=1157259159 --deterministic-mode --test-type=gpu --disable-search-engine-choice-screen --disable-session-crashed-bubble --hide-crash-restore-bubble --suppress-message-center-popups --disable-client-side-phishing-detection --disable-domain-reliability --disable-component-update --disable-datasaver-prompt --disable-hang-monitor --disable-speech-synthesis-api --disable-speech-api --disable-print-preview --safebrowsing-disable-auto-update --deny-permission-prompts --disable-external-intent-requests --disable-notifications --disable-desktop-notifications --noerrdialogs --disable-popup-blocking --disable-prompt-on-repost --silent-debugger-extension-api --block-new-web-contents --metrics-recording-only --disable-breakpad --use-fake-device-for-media-stream --force-gpu-mem-available-mb=4096 --password-store=basic --use-mock-keychain --disable-cookie-encryption --allow-legacy-extension-manifests --disable-gesture-requirement-for-media-playback --font-render-hinting=none --force-color-profile=srgb --disable-partial-raster --disable-skia-runtime-opts --disable-2d-canvas-clip-aa --disable-lazy-loading --disable-renderer-backgrounding --disable-background-networking --disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-ipc-flooding-protection --disable-extensions-http-throttling --disable-field-trial-config --disable-back-forward-cache --headless=new --window-size=1440,2000 '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 ArchiveBox/0.8.6rc2 (+https://github.com/ArchiveBox/ArchiveBox/)' --user-data-dir=/Volumes/NVME/Users/squash/Local/Code/archiveboxes/ArchiveBox7/archivebox/pkgs/abx-plugin-chrome/abx_plugin_chrome/personas/Default/chrome_profile --profile-directory=Default --screenshot https://example.com


async function main() {
    const launch_args = await exec('node ./config.py CHROME_ARGS').split('\n')
    const browser = await puppeteer.launch({
        headless: true,
        args: launch_args,
    })

    const page = await browser.newPage()
    await page.goto(url)
    await page.screenshot({path: 'screenshot.png', fullPage: true})

    await browser.close()
}

main()
