tring';
import { Readable } from 'node:stream';
import { finished } from 'node:stream/promises';
import { URL } from 'node:url';
import util from 'node:util';
const exec = util.promisify(child_process.exec);

import { Readability } from '@mozilla/readability';
import FileCookieStore from '@root/file-cookie-store';
import merge from 'deepmerge';
import { createCursor, getRandomPagePoint } from 'ghost-cursor';
import { JSDOM, VirtualConsole } from 'jsdom';
import mime from 'mime-types';
import ToughCookie from 'tough-cookie';
import unzip from 'unzip-crx-3';

import puppeteer from 'puppeteer';
import { Browser, Page, Cookie, HTTPResponse } from 'puppeteer';
import { Cluster } from 'puppeteer-cluster';
import PupeteerExtra from "puppeteer-extra";
import Stealth#!/usr/bin/env node --env-file .env
// https://gist.github.com/pirate/d9a350e83025a1e6cf452cddd815d0d4

// npm install request node-request minimist deepmerge mime-types decompress puppeteer-extra puppeteer-extra-plugin-repl puppeteer-extra-plugin-user-preferences puppeteer-extra-plugin-recaptcha puppeteer-extra-plugin-stealth puppeteer-screen-recorder puppeteer-cluster ghost-cursor @mozilla/readability jsdom unzip-crx-3 node-fetch@2 


import assert from 'node:assert/strict';
import { Buffer } from 'node:buffer';
import child_process from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { createServer } from 'node:http';
import os from 'node:os';
import path from 'node:path';
import querystring from 'node:querysPlugin from "puppeteer-extra-plugin-stealth";
import PrefsPlugin from 'puppeteer-extra-plugin-user-preferences';
import { PuppeteerScreenRecorder } from 'puppeteer-screen-recorder';
// import RecaptchaPlugin from 'puppeteer-extra-plugin-recaptcha';
// import ReplPlugin from 'puppeteer-extra-plugin-repl';

const __dirname = import.meta.dirname

import { getDatabase } from './models/init-models.js';
const { Tag, Snapshot, ArchiveResult } = await getDatabase({ dbpath: './index.sqlite3' })


// move mitm CA cert into /usr/local/share/ca-certificates/mitmproxy-ca-cert.crt
// update-ca-certificates


const ANSI = {
    reset: "\x1b[0m",
    blue: "\x1b[34m",
    black: "\x1b[30m",
}

/************************* Main Input Arguments *******************************/
let URLS = [
    // 'chrome://about',
    // 'chrome://system/#chrome_root_store',

    'https://facebook.com/815781663692514/?comment_id=1508571679703640',
    'https://www.instagram.com/p/CrTY1fENHr5/',
    'https://www.tiktok.com/@zemmour_eric/video/7342474065598319904?cid=7343316616878490400',
    'https://twitter.com/DZasken68678/status/1799833933271687304',
    'https://t.me/IONONMIARRENDOGROUP/13598',
    'https://www.youtube.com/watch?v=rpD0qgzlCms',
    'https://www.aap.com.au/factcheck/aboriginal-lands-claim-a-total-abdication-of-facts/',


    'https://gologin.com/check-browser',
    'https://arh.antoinevastel.com/bots/areyouheadless',

    'https://2captcha.com/demo/hcaptcha',
    'https://2captcha.com/demo/cloudflare-turnstile',
    'https://2captcha.com/demo/recaptcha-v3',
    'https://ipinfo.io/',

    // 'https://2captcha.com/demo/recaptcha-v2',
    // 'https://2captcha.com/demo/keycaptcha',
    // 'https://browserleaks.com/canvas',
    // 'https://bot.incolumitas.com/#botChallenge',
    // 'https://infosimples.github.io/detect-headless/',
    // 'https://coveryourtracks.eff.org/',
    // 'https://fingerprint.com/demo/',
    // 'https://nowsecure.nl',
    // 'https://abrahamjuliot.github.io/creepjs/',
    // 'https://scrapfly.io/web-scraping-tools/http2-fingerprint',
    // 'https://scrapfly.io/web-scraping-tools/browser-fingerprint',
    // 'https://scrapfly.io/web-scraping-tools/ja3-fingerprint',
    // 'https://scrapfly.io/web-scraping-tools/canvas-fingerprint',
    // 'https://scrapfly.io/web-scraping-tools/webgl-fingerprint',
    // 'https://scrapfly.io/web-scraping-tools/audio-fingerprint',
    // 'https://scrapfly.io/web-scraping-tools/screen-fingerprint',
    // 'https://web-scraping.dev/',


    // 'https://example.com',
    // 'https://www.okta.com/',
    // 'https://www.webflow.com/',
    // 'https://docker-compose.archivebox.io',
    // 'https://www.reddit.com/r/AskReddit/comments/1br0q9b/what_was_ok_10_years_ago_but_isnt_today/',
    // 'https://www.quora.com/Is-the-website-2Captcha-true-or-fake-with-paying-money-for-working-on-it',
    // 'https://x.com/yawnzzcalo7/status/1747853178849435894',
    // 'https://twitter.com/yawnzzcalo7/status/1747853178849435894',
    // 'https://rachdele.substack.com/p/is-the-job-market-dying',
    // 'https://www.flowradar.com/cloneables/mouse-image-trail-effect',
    // 'https://wrong.host.badssl.com/',
    // 'http://docker-compose.archivebox.io',
    // 'https://pptr.dev/api/puppeteer.page.setrequestinterception',
    // 'https://blog.sweeting.me#Writing',
    // 'https://github.com/yarnpkg/yarn/issues/9005',

    // 'https://archive.md/739Oc',
    // 'https://archive.md/Oc72d',
    // 'https://archive.vn/fPUBe',
    // 'https://archive.vn/mRz4P',
    // 'https://archive.vn/Qct6Y',
    // 'https://archive.vn/sv50h',
    // 'https://facebook.com/815781663692514/?comment_id=1508571679703640',
    // 'https://facebook.com/815781663692514/?comment_id=924451748966499',
    // 'https://www.facebook.com/wayne.brennan.528/posts/pfbid02fvxFppng2WsHMavhBa62cXizCBGdmPQRH3CMhac79qzS5C1ADaSNC587d3u6qVbkl',
    // 'https://www.facebook.com/wildeprods/posts/pfbid02YEPfoB7pZqMNzE4y2MpYSQbRAzASquvHyEMzHqrNngJCSL7onEg2jnsqS6epcQHWl',
    // 'https://t.me/aubontouite_francais/9493',
    // 'https://t.me/BC_BLACKMIROR/5044',
    // 'https://t.me/IONONMIARRENDOGROUP/14004',
    // 'https://t.me/newsfactory_pl/51014',
    // 'https://t.me/oliverjanich/132574',
    // 'https://t.me/tomaszgryguc/10449',
    // 'https://t.me/amigosDisidentes/123177',
    // 'https://twitter.com/1nfiltr4do_NN/status/1767238399943991389',
    // 'https://twitter.com/4lmondcookie/status/1748519205438111914',
    // 'https://twitter.com/4olll1ke/status/1753796944827199766',
    // 'https://twitter.com/yeokiloss/status/1754908226179502345',
    // 'https://twitter.com/YoungWaifLover/status/1735667278090297561',
    // 'https://twitter.com/Z_Pour_Demain/status/1766133730278605182',
    // 'https://www.aap.com.au/factcheck/aboriginal-lands-claim-a-total-abdication-of-facts/',
    // 'https://www.aap.com.au/factcheck/absurd-albanese-clip-fools-voice-voters/',
    // 'https://www.instagram.com/_the.forgotten.ones/p/CQQDyoqhsF6/',
    // 'https://www.instagram.com/p/CqSM_f9MR4b/',
    // 'https://www.instagram.com/p/CqSQgf1sv8B/',
    // 'https://instagram.com/p/B-Q22Z_pxyC/',
    // 'https://www.tiktok.com/@zitatezurzeit/photo/7342474065598319904?cid=7343316616878490400',
    // 'https://tiktok.com/@zitatezurzeit/photo/7342474065598319904?cid=7343316616878490400',
    // 'https://www.youtube.com/watch?v=rpD0qgzlCms',
]

const isTruthy = (env_value) => ['1', 'yes', 'true'].includes(env_value?.toLowerCase() || 'false')

/********************** Config: General High-Level Options ********************/

const PASSIVE_ARCHIVING = isTruthy(process.env.PASSIVE_ARCHIVING)
const CHROME_CLUSTER = isTruthy(process.env.CHROME_CLUSTER)
const CHROME_CLUSTER_WORKERS = 4

const API_SERVER_HOST = '0.0.0.0'
const API_SERVER_PORT = 9595
const CHROME_DEBUG_PORT = 9222                                    // 9222 is default, or use 0 for random port

/********************** Config: Keys & Secrets ********************************/

const API_KEY_2CAPTCHA = process.env.API_KEY_2CAPTCHA || 'YOUR_API_KEY_HERE'
const FLARESOLVERR_API_ENDPOINT = process.env.FLARESOLVERR_API_ENDPOINT || "http://localhost:8191/v1"

const ACTIVE_PERSONA = process.env.ACTIVE_PERSONA || 'Default'
const CHROME_PROFILE_USER = process.env.CHROME_PROFILE_USER || 'Default'
const LOAD_AUTH_STORAGE = isTruthy(process.env.LOAD_AUTH_STORAGE)
const SAVE_AUTH_STORAGE = isTruthy(process.env.SAVE_AUTH_STORAGE)

/********************** Config: Data Dir Locations ****************************/

const SRC_DIR = path.resolve(__dirname)
const DATA_DIR = process.env.DATA_DIR || await fs.promises.realpath(path.join(SRC_DIR, 'data'))
const INDEXES_DIR = path.join(DATA_DIR, 'index')
const ARCHIVE_DIR = path.join(DATA_DIR, 'archive')
if (!fs.existsSync(ARCHIVE_DIR))
    throw 'Could not find data/archive, are you running in the right pwd?'

const PERSONA_DIR = path.join(DATA_DIR, 'personas', ACTIVE_PERSONA)
const CHROME_PROFILE_PATH = path.join(PERSONA_DIR, 'chrome_profile')
const CHROME_DOWNLOADS_DIR = path.join(PERSONA_DIR, 'chrome_downloads')
const CHROME_EXTENSIONS_DIR =  path.join(PERSONA_DIR, 'chrome_extensions')
const CHROME_EXTENSIONS_JSON_PATH = path.join(CHROME_EXTENSIONS_DIR, 'extensions.json')
const AUTH_JSON_PATH = path.join(PERSONA_DIR, 'auth.json')
const COOKIES_TXT_PATH = path.join(PERSONA_DIR, 'cookies.txt')
const SPEEDTESTS_DIR = path.join(PERSONA_DIR, 'speedtests')
// const CHROME_PROFILE_IMPORT_USER = 'Profile 1'
// const CHROME_PROFILE_IMPORT_PATH = '/Volumes/NVME/Users/squash/Library/Application Support/Google/Chrome'

// chrome profile / persona directories
fs.mkdirSync(PERSONA_DIR, {recursive: true})
fs.mkdirSync(SPEEDTESTS_DIR, {recursive: true})
fs.mkdirSync(CHROME_PROFILE_PATH, {recursive: true})
fs.mkdirSync(CHROME_EXTENSIONS_DIR, {recursive: true})
fs.mkdirSync(CHROME_DOWNLOADS_DIR, {recursive: true})

// cruft directories
const ORPHANS_DIR = path.join(DATA_DIR, 'orphans')
const PARTIALS_DIR = path.join(DATA_DIR, 'partials')
const DUPLICATES_DIR = path.join(DATA_DIR, 'duplicates')
await fs.promises.mkdir(ORPHANS_DIR, {recursive: true})
await fs.promises.mkdir(PARTIALS_DIR, {recursive: true})
await fs.promises.mkdir(DUPLICATES_DIR, {recursive: true})

/********************** Config: Viewport Setup Opts ***************************/

// Config: Viewport
const DEFAULT_TIMEOUT = 20_000
const DEFAULT_GEOLOCATION = {latitude: 59.95, longitude: 30.31667}
const DEFAULT_USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
const DEFAULT_ASPECT_RAIO = 16/9       // recommended: 16:9       (most common desktop window aspect ratio)
const SCREENSHOT_ASPECT_RATIO = 4/3    // recommended: 4:3        (easier to use as thumbnails when square-ish)
const DEFAULT_WINDOW_WIDTH = 1920      // recommended: 1920x1080p (1080p screenshots)
const DEFAULT_WINDOW_HEIGHT = Math.floor(DEFAULT_WINDOW_WIDTH/DEFAULT_ASPECT_RAIO)
const DEFAULT_VIEWPORT = {
    width: DEFAULT_WINDOW_WIDTH,
    height: DEFAULT_WINDOW_HEIGHT,            
    deviceScaleFactor: 2,              // 2 gives much sharper text in screenshots/pdfs/etc but uses more CPU/GPU
    isMobile: false,
    hasTouch: false,
    isLandscape: false,
}
const DEFAULT_COLOR_SCHEME = 'light'
const DEFAULT_HEADERS = {
    // requires frequent tweaking to remain undetected by cloudflare/recaptcha/etc.
    // 'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    // 'accept-encoding': 'gzip, deflate, br, zstd',
    // 'accept-language': accept_language,
    // 'cache-Control': no_cache ? 'no-cache' : '',
    // 'dnt': '1',
    'sec-ch-ua': '"Google Chrome";v="122", "Not:A-Brand";v="8", "Chromium";v="122"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'connection-rtt': '50',
    // 'pragma': no_cache ? 'no-cache' : '',
    // 'sec-fetch-dest': 'document',
    // 'sec-fetch-mode': 'navigate',
    // 'sec-fetch-site': 'none',
    // 'sec-fetch-user': '?1',
    // // 'upgrade-insecure-requests': '1',     // breaks some sites, e.g. https://www.flowradar.com/cloneables/mouse-image-trail-effect
    // 'user-agent': user_agent,
}

const DEFAULT_REFERRERS = ["https://www.google.com", "https://www.facebook.com", "https://www.instagram.com"]

/****************** Config: Human Behavior Emulation **************************/

const SCROLL_LIMIT = 20;    // e.g. 30 = 30 * (1000px/2s) => 30,000px scrolled in 60sec
const SCROLL_DELAY = 1350;  // interval per scroll, e.g. 2000 = 2sec to travel 1 * SCROLL_DISTANCE
const SCROLL_DISTANCE = DEFAULT_VIEWPORT.height - 100;  // make sure this is slightly less than viewport height so there is some overlap to make stitching easier

/********************** Config: URL Rewriting *********************************/
const URL_REWRITES = [
    // replacements should come first
    // {
    //     idx: 0,
    //     pattern: /\/\/(www\.)?x\.com/gi,
    //     replacement: '//$1twitter.com/',
    //     // TODO: scope: 'hostname',
    // },
    // {
    //     idx: 1,
    //     pattern: /\/\/(www\.)?twitter\.com/gi,
    //     replacement: '//$1nitter.net',
    //     // TODO: scope: 'hostname',
    // },

    // // blocks should come at the end
    // {
    //     idx: 999,
    //     pattern: /\/\/(www\.)?notallowed\.com/gi,
    //     replacement: '',
    //     // TODO: scope: 'href',
    // },
]
const URL_SCHEMES_IGNORED = [
    '',                     // no scheme is also invalid (e.g. opening a new tab page without any url yet)
    'chrome',
    'chrome-extension',
    'chrome-untrusted',
    'file',
    'data',
    'about',
]


/**************** Load existing data/archive/<timestamp> snapshots *************/

const snapshots = await Snapshot.findAll({ attributes: ['id', 'timestamp', 'url'] })   // include: { model: ArchiveResult, as: 'archiveresults' }, });
const results = await ArchiveResult.findAll({ attributes: ['id', 'snapshot_id', 'extractor', 'start_ts'] })   // include: { model: Snapshot, as: 'snapshot' }, });
globalThis.snapshots = snapshots
globalThis.results = results
console.log(`[💿] Found ${snapshots.length} existing snapshots in index.sqlite3...`)
console.log(`[💿] Found ${results.length} existing results in index.sqlite3...`)
// debugger;

const locateExistingSnapshots = (archive_dir) => {
    const urls_to_dirs = {}
    // for each data/archive/<timestamp>/index.json found, store {url: data/archive/<timestamp>}
    for (const snapshot_dir of fs.readdirSync(archive_dir)) {
        const snapshot_json = path.join(archive_dir, snapshot_dir, 'index.json')
        if (fs.existsSync(snapshot_json)) {
            const {url, archive_path} = JSON.parse(fs.readFileSync(snapshot_json, 'utf-8'))
            if (!snapshot_dir.includes(archive_path.replace('archive/', '')))
                throw 'Found incorrect index.json inside snapshot dir' + snapshot_dir
            if (url && url.includes('://')) {
                urls_to_dirs[url] = path.join(archive_dir, snapshot_dir)
            }
        }
    }
    return urls_to_dirs
}

let SNAPSHOT_DIRS_BY_URL = locateExistingSnapshots(ARCHIVE_DIR)

let all_snap_dirs = (await fs.promises.readdir(ARCHIVE_DIR))
// const orphan_snap_dirs = all_snap_dirs.filter(dirname => dirname.startsWith('19999'))

// // scan through existing snapshot dirs, move orphans to orphans/ or correct archive/<snapid>
// for (const snap_id of orphan_snap_dirs) {
//     if (snap_id.startsWith('.')) continue
//     const src_dir = path.join(ARCHIVE_DIR, snap_id)
//     let src_path = src_dir

//     assert((await fs.promises.stat(src_dir)).isDirectory())
//     let dest_path = null

//     const orphan_metrics_path = path.join(src_dir, 'metrics.json')
//     if (fs.existsSync(orphan_metrics_path)) {
//         const orphan_metrics = JSON.parse(await fs.promises.readFile(orphan_metrics_path, 'utf-8'))
//         const url = orphan_metrics.url || orphan_metrics.URL
//         const version = orphan_metrics.VERSION || versionStrFromDate(orphan_metrics.start_time)
        
//         // move all bare files into ./versions/YYYYMMDD/* and symlink ./* to latest version
//         await symlinkBestSnapshotResults(src_dir)

//         dest_path = SNAPSHOT_DIRS_BY_URL[url]
//         const dest_id = dest_path?.split('/').at(-1)
        
//         if (dest_id && (dest_id != snap_id)) {
//             if (fs.existsSync(dest_path)) {
//                 console.log(`    - moving duplicate snap_dir ${src_dir} -> ${dest_path}`)
//             } else {
//                 console.log(`   - moving valid snap_dir ${src_dir} -> ${dest_path}`)
//             }
//         } else if (dest_id == snap_id) {
//             continue
//         } else {
//             dest_path = path.join(ORPHANS_DIR, snap_id)
//             console.log(`   - moving orphan snap_dir ${src_dir} -> ${dest_path}`)
//         }
//     } else {
//         // corrupt/par
//         dest_path = path.join(PARTIALS_DIR, snap_id)
//         console.log(`   - moving parial snap_dir ${src_dir} -> ${dest_path}`)
//     }
//     if (dest_path) {
//         for (const version_dir of (await fs.promises.readdir(path.join(src_path, 'versions')))) {
//             const version_src = path.join(src_path, 'versions', version_dir)
//             const version_dst = path.join(dest_path, 'versions', version_dir)

//             // move all bare files into ./versions/YYYYMMDD/* and symlink ./* to latest version
//             await symlinkBestSnapshotResults(dest_path)

//             assert(!fs.existsSync(version_dst))
//             await fs.promises.rename(version_src, version_dst)
//             console.log('    - ', version_src, '--->', version_dst)
//         }
//         await fs.promises.rename(src_dir, path.join(PARTIALS_DIR, snap_id))
//         await symlinkBestSnapshotResults(dest_path)
//     }
// }

// const duplicate_snap_dirs = (await fs.promises.readdir(DUPLICATES_DIR)).filter(dirname => dirname.startsWith('19999'))
// for (const snap_id of duplicate_snap_dirs) {
//     const src_dir = path.join(DUPLICATES_DIR, snap_id)
//     const metrics = JSON.parse(await fs.promises.readFile(path.join(src_dir, 'metrics.json'), 'utf-8'))
// }

// all_snap_dirs = (await fs.promises.readdir(ARCHIVE_DIR))
// for (const snap_id of all_snap_dirs) {
//     if (snap_id.startsWith('.')) continue
//     const snap_dir = path.join(ARCHIVE_DIR, snap_id)
//     const metrics_path = path.join(snap_dir, 'metrics.json')
//     if (fs.existsSync(metrics_path)) {
//         // console.log('    - updating snap_dir', snap_dir)
//         await symlinkBestSnapshotResults(snap_dir)
//     }
// }
// SNAPSHOT_DIRS_BY_URL = locateExistingSnapshots(ARCHIVE_DIR)


fs.writeFileSync(path.join(DATA_DIR, 'queue.csv'), '')

const snapIdFromDir = (dir_path) =>
    dir_path.split('/archive/').at(-1)

const snapshot_dir_list = (
    Object.entries(SNAPSHOT_DIRS_BY_URL)
        .sort(([_ak, a], [_bk, b]) =>
            Number(snapIdFromDir(b)) - Number(snapIdFromDir(a)))
        .reverse())

for (const [existing_url, snapshot_dir] of snapshot_dir_list) {
    // if (existing_url.startsWith('https://www.facebook.com/')) {
    const is_desired_url = !(existing_url.includes('facebook.com/') || existing_url.includes('instagram.com/'))
    const already_archived = false   // fs.existsSync(path.join(SNAPSHOT_DIRS_BY_URL[existing_url], 'versions'))
    if (is_desired_url && !already_archived) {
        // URLS.push(existing_url)
        fs.appendFileSync(
            path.join(DATA_DIR, 'queue.csv'),
            `${SNAPSHOT_DIRS_BY_URL[existing_url]},${existing_url}\n`,
            'utf-8',
        )
    }
}
URLS = [...new Set(URLS)]
console.log('[+] Added', URLS.length, 'existing urls to queue...')


/********************** Config: Output Paths **********************************/
// const TASK_PATH             = (url)  => path.join(DATA_DIR, 'results', `${hashCode(url)}`)
const TASK_PATH             = (url)  => SNAPSHOT_DIRS_BY_URL[url] || path.join(ARCHIVE_DIR, `1999999999.${hashCode(url)}`)
// const TASK_PATH                = (url)  => {
//     const existing_snap_dir = SNAPSHOT_DIRS_BY_URL[url]
//     assert(existing_snap_dir, `Could not find existing snapshot dir for ${url}`)
//     return existing_snap_dir
// }

const OUTPUT_PATH           = (page, filename, extname='') => 
                                        path.join(TASK_PATH(page._original_url), `${filename}${extname}`)

const SSL_PATH              = (page) => OUTPUT_PATH(page, 'ssl.json')
const CONSOLELOG_PATH       = (page) => OUTPUT_PATH(page, 'console.log')
const HEADERS_PATH          = (page) => OUTPUT_PATH(page, 'headers.json')
const REDIRECTS_PATH        = (page) => OUTPUT_PATH(page, 'redirects.json')
const REQUESTS_PATH         = (page) => OUTPUT_PATH(page, 'requests.json')
const TRACE_PATH            = (page) => OUTPUT_PATH(page, 'trace.json')
const METRICS_PATH          = (page) => OUTPUT_PATH(page, 'metrics.json')
const OUTLINKS_PATH         = (page) => OUTPUT_PATH(page, 'outlinks.json')
const SEO_PATH              = (page) => OUTPUT_PATH(page, 'seo.json')
const FAVICON_PATH          = (page) => OUTPUT_PATH(page, 'favicon.json')
const TITLE_PATH            = (page) => OUTPUT_PATH(page, 'title.txt')
const BODYTEXT_PATH         = (page) => OUTPUT_PATH(page, 'body.txt')
const PANDOC_PATH           = (page) => OUTPUT_PATH(page, 'pandoc.md')
const READABILITY_PATH      = (page) => OUTPUT_PATH(page, 'readability.json')
const ACCESIBILITY_PATH     = (page) => OUTPUT_PATH(page, 'accessibility.json')
const DOM_PATH              = (page) => OUTPUT_PATH(page, 'dom.html')
const PDF_PATH              = (page) => OUTPUT_PATH(page, 'output.pdf')
const SCREENSHOT_PATH       = (page) => OUTPUT_PATH(page, 'screenshot.png')
const SCREENSHOT_JPG_PATH   = (page) => OUTPUT_PATH(page, 'screenshot.jpg')
const AIQA_PATH             = (page) => OUTPUT_PATH(page, 'aiqa.json')
const SINGLEFILE_PATH       = (page) => OUTPUT_PATH(page, 'singlefile.html')
const YTDLP_PATH            = (page) => OUTPUT_PATH(page, 'media/')
const GALLERYDL_PATH        = (page) => OUTPUT_PATH(page, 'photos/')
const SCREENRECORDING_PATH  = (page) => OUTPUT_PATH(page, 'screenrecording.mp4')
const SCREENRECORDGIF_PATH  = (page) => OUTPUT_PATH(page, 'screenrecording.gif')
const RESPONSES_PATH        = (page) => OUTPUT_PATH(page, 'responses')
const RAW_PATH              = (page) => OUTPUT_PATH(page, 'raw')



/********************** Config: Chrome Extensions *****************************/

interface ChromeExtension {
    name: string
    webstore_id: string
}
interface LoadedChromeExtension extends ChromeExtension {
    id?: string
    webstore_url?: string
    crx_url?: string
    crx_path?: string
    unpacked_path?: string
    read_manifest?: () => any
    read_version?: () => string | null
}

const CHROME_EXTENSIONS: LoadedChromeExtension[] = [
    // Content access / unblocking / blocking plugins
    {webstore_id: 'ifibfemgeogfhoebkmokieepdoobkbpo', name: 'captcha2'},                 // https://2captcha.com/blog/how-to-use-2captcha-solver-extension-in-puppeteer
    {webstore_id: 'edibdbjcniadpccecjdfdjjppcpchdlm', name: 'istilldontcareaboutcookies'},
    {webstore_id: 'cjpalhdlnbpafiamejdnhcphjbkeiagm', name: 'ublock'},
    // {webstore_id: 'mlomiejdfkolichcflejclcbmpeaniij', name: 'ghostery'},
    // {webstore_id: 'mnjggcdmjocbbbhaepdhchncahnbgone', name: 'sponsorblock'},
    // {webstore_id: 'iplffkdpngmdjhlpjmppncnlhomiipha', name: 'unpaywall'},
    // {webstore_id: 'gofocbepaccnkpphbgjpolififgcakhn', name: 'spaywallnews'},
    
    // Archiving plugins
    {webstore_id: 'mpiodijhokgodhhofbcjdecpffjipkle', name: 'singlefile'},
    // {webstore_id: 'fpeoodllldobpkbkabpblcfaogecpndd', name: 'archivewebpage'},
    // {webstore_id: 'niloccemoadcdkdjlinkgdfekeahmflj', name: 'pocket'},
    // {webstore_id: 'kenncghfghgolcbmckhiljgaabnpcaaa', name: 'warcreate'},
    // {webstore_id: 'jjndjgheafjngoipoacpjgeicjeomjli', name: 'puppeteerstream'},

    // Utilities for humans setting up/viewing/debugging the archiving session
    // {webstore_id: 'aeblfdkhhhdcdjpifhhbdiojplfjncoa', name: '1password'},
    // {webstore_id: 'fngmhnnpilhplaeedifhccceomclgfbg', name: 'editthiscookie'},
    // {webstore_id: 'cgfpgnepljlgenjclbekbjdlgcodfmjp', name: 'simpletabsorter'},
    
    // Scripting/automation plugins
    // {webstore_id: 'jinjaccalgkegednnccohejagnlnfdag', name: 'violentmonkey'},
    // {webstore_id: 'infppggnoaenmfagbfknfkancpbljcca', name: 'automa'},
    // {webstore_id: 'pfegffhjcgkneoemnlniggnhkfioidjg', name: 'screenscraper'},
]

/******************** Config: Chrome Profile Preferences **********************/

// https://niek.github.io/chrome-features/
const CHROME_DISABLED_COMPONENTS = [
    'Translate',
    'AcceptCHFrame',
    'OptimizationHints',
    'ProcessPerSiteUpToMainFrameThreshold',
    'InterestFeedContentSuggestions',
    'CalculateNativeWinOcclusion',
    'BackForwardCache',
    'HeavyAdPrivacyMitigations',
    'LazyFrameLoading',
    'ImprovedCookieControls',
    'PrivacySandboxSettings4',
    'AutofillServerCommunication',
    'CertificateTransparencyComponentUpdater',
    'DestroyProfileOnBrowserClose',
    'CrashReporting',
    'OverscrollHistoryNavigation',
    'InfiniteSessionRestore',
    //'LockProfileCookieDatabase',      // disabling allows multiple chrome instances to concurrently modify profile, but might make chrome much slower https://github.com/yt-dlp/yt-dlp/issues/7271  https://issues.chromium.org/issues/40901624
]

const CHROME_PREFERENCES_EXTRA = {}
const CHROME_PREFERENCES_DEFAULT = {
    // https://chromium.googlesource.com/chromium/src/+/32352ad08ee673a4d43e8593ce988b224f6482d3/chrome/common/pref_names.cc
    homepage: 'about:blank',                        // doesn't work here, managed by Secure Preferences
    homepage_is_newtabpage: false,                  // doesn't work here, managed by Secure Preferences
    session: {                                      // doesn't work here, managed by Secure Preferences
        restore_on_startup: 4,                      // doesn't work here, managed by Secure Preferences
        startup_urls: 'about:blank',                // doesn't work here, managed by Secure Preferences
    },
    default_apps: 'noinstall',
    browser: {
        confirm_to_quit: false,
        enable_spellchecking: false,
        check_default_browser: false,
        show_update_promotion_info_bar: false,
    },
    profile: {
        // name: 'ArchiveBox Persona: Default',    // doesnt work to change display name, not sure why
        // using_default_name: false,
        exited_cleanly: true,
        default_content_setting_values: {
          automatic_downloads: 1,
        },
    },
    bookmark_bar: {show_on_all_tabs: false},
    safebrowsing: {enabled: false},
    search: {suggest_enabled: false},
    download: {
        prompt_for_download: false,
        open_pdf_in_system_reader: true,
        // default_directory: CHROME_DOWNLOADS_DIR || path.join(__dirname, 'downloads'),
    },
    select_file_dialogs: {allowed: false},
    autofill: {save_data: false},
    printing: {enabled: false},
    message_center: {welcome_notification_dismissed_local: true},
    extensions: {
        ui: {
            developer_mode: true,
            dismissed_adt_promo: true,
        },
        // pinned_extensions: CHROME_EXTENSIONS?.map(({id}) => id) || [],
    },
    webkit: {
        webprefs: {
            javascript_enabled: true,
            minimum_font_size: 9,
            // default_font_size: 12,
            // web_security_enabled: false,
            // allow_displaying_insecure_content: true,
            // allow_running_insecure_content: true,
            java_enabled: true,
            loads_images_automatically: true,
        },
    },
    settings: {
        multi_profile_never_show_intro: true,
        multi_profile_warning_show_dismissed: true,
        first_run_tutorial_shown: true,
    },
    plugins: {
        always_open_pdf_externally: true,
    },
}

const CHROME_PREFERENCES_PATH = path.join(CHROME_PROFILE_PATH, 'Default', 'Preferences')

const getChromePreferences = ({CHROME_PREFERENCES_DEFAULT, CHROME_PREFERENCES_EXTRA, CHROME_EXTENSIONS, CHROME_DOWNLOADS_DIR}) =>
    merge.all([CHROME_PREFERENCES_DEFAULT, CHROME_PREFERENCES_EXTRA, {
        extensions: {
            pinned_extensions: CHROME_EXTENSIONS?.map(({id}) => id) || [],
        },
        download: {
            default_directory: CHROME_DOWNLOADS_DIR || path.join(__dirname, 'downloads'),
        },
    }])

function applyChromePreferences(puppeteer, prefs_path, preferences) {
    if (fs.existsSync(prefs_path)) {
        const preferences_existing = JSON.parse(fs.readFileSync(prefs_path, 'utf-8'))
        const preferences_merged = merge(preferences_existing, preferences)
        // console.log(JSON.stringify(preferences_merged, null, 4))
        fs.writeFileSync(prefs_path, JSON.stringify(preferences_merged))    
    } else {
        // otherwise profile has not been created yet, use plugin instead (plugin only works on first creation)
        puppeteer.use(PrefsPlugin({userPrefs: preferences}))
    }
    return puppeteer
}


/******************** Config: Chrome Launch Args ******************************/

const CHROME_ARGS_DEFAULT = [
    // Headless behavior tuning, determinstic behavior settings
    // '--headless=new',
    '--test-type',
    '--test-type=gpu',                                // https://github.com/puppeteer/puppeteer/issues/10516
    '--deterministic-mode',
    '--js-flags=--random-seed=1157259159',            // make all JS random numbers deterministic by providing a seed
    '--allow-pre-commit-input',                       // allow JS mutations before page rendering is complete
    '--disable-blink-features=AutomationControlled',  // hide the signatures that announce browser is being remote-controlled
    '--enable-automation',                            // <- DONT USE THIS, it makes you easily detectable / blocked by cloudflare
    // `--proxy-server=https://43.159.28.126:2334:u7ce652b7568805c4-zone-custom-region-us-session-szGWq3FRU-sessTime-60:u7ce652b7568805c4`,      // send all network traffic through a proxy https://2captcha.com/proxy
    // `--proxy-bypass-list=127.0.0.1`,

    // Docker-specific options
    // https://github.com/GoogleChrome/lighthouse-ci/tree/main/docs/recipes/docker-client#--no-sandbox-issues-explained
    // '--no-sandbox',                                   // rely on docker sandboxing in docker, otherwise we need cap_add: SYS_ADM to use host sandboxing
    // '--disable-gpu-sandbox',
    // '--disable-setuid-sandbox',
    // '--disable-dev-shm-usage',                     // docker 75mb default shm size is not big enough, disabling just uses /tmp instead
    // '--no-xshm',

    // Profile data dir setup
    // chrome://profile-internals
    `--user-data-dir=${CHROME_PROFILE_PATH}`,
    `--profile-directory=${CHROME_PROFILE_USER}`,
    '--password-store=basic',                            // use mock keychain instead of OS-provided keychain (we manage auth.json instead)
    '--use-mock-keychain',
    '--disable-cookie-encryption',                       // we need to be able to write unencrypted cookies to save/load auth.json
    // '--disable-sync',                                 // don't try to use Google account sync features

    // Extensions
    // chrome://inspect/#extensions
    // `--load-extension=${CHROME_EXTENSIONS.map(({unpacked_path}) => unpacked_path).join(',')}`,  // not needed when using existing profile that already has extensions installed
    `--allowlisted-extension-id=${CHROME_EXTENSIONS.map(({ webstore_id }) => webstore_id).join(',')}`,
    '--allow-legacy-extension-manifests',

    // Browser window and viewport setup
    // chrome://version
    // `--user-agent="${DEFAULT_USER_AGENT}"`,
    // `--window-size=${DEFAULT_VIEWPORT.width},${DEFAULT_VIEWPORT.height}`,
    '--window-position=0,0',
    '--hide-scrollbars',                               // hide scrollbars because otherwise they show up in screenshots
    '--install-autogenerated-theme=169,32,85',         // red border makes it easier to see which chrome window is archivebox's
    '--autoplay-policy=no-user-gesture-required',      // auto-start videos so they trigger network requests + show up in outputs 
    '--disable-gesture-requirement-for-media-playback',
    '--lang=en-US,en;q=0.9',

    // DANGER: JS isolation security features (to allow easier tampering with pages during archiving)
    // chrome://net-internals
    // '--disable-web-security',                              // <- WARNING, breaks some sites that expect/enforce strict CORS headers (try webflow.com)
    // '--disable-features=IsolateOrigins,site-per-process', // useful for injecting JS, but some very strict sites can panic / show error pages when isolation is disabled (e.g. webflow.com)
    // '--allow-running-insecure-content',                   // Breaks CORS/CSRF/HSTS etc., useful sometimes but very easy to detect
    // '--allow-file-access-from-files',                     // <- WARNING, dangerous, allows JS to read filesystem using file:// URLs

    // // DANGER: Disable HTTPS verification
    // '--ignore-certificate-errors',
    // '--ignore-ssl-errors',
    // '--ignore-certificate-errors-spki-list',
    // '--allow-insecure-localhost',

    // IO: stdin/stdout, debug port config
    // chrome://inspect
    '--log-level=2',                                  // 1=DEBUG 2=WARNING 3=ERROR
    '--enable-logging=stderr',
    '--remote-debugging-address=0.0.0.0',
    `--remote-debugging-port=${CHROME_DEBUG_PORT}`,

    // GPU, canvas, text, and pdf rendering config
    // chrome://gpu
    '--enable-webgl',                                 // enable web-gl graphics support
    '--font-render-hinting=none',                     // make rendering more deterministic by ignoring OS font hints, may also need css override, try:    * {text-rendering: geometricprecision !important; -webkit-font-smoothing: antialiased;}
    '--force-color-profile=srgb',                     // make rendering more deterministic by using consitent color profile, if browser looks weird, try: generic-rgb
    '--disable-partial-raster',                       // make rendering more deterministic (TODO: verify if still needed)
    '--disable-skia-runtime-opts',                    // make rendering more deterministic by avoiding Skia hot path runtime optimizations
    '--disable-2d-canvas-clip-aa',                    // make rendering more deterministic by disabling antialiasing on 2d canvas clips
    // '--disable-gpu',                                  // falls back to more consistent software renderer
    // // '--use-gl=swiftshader',                        <- DO NOT USE, breaks M1 ARM64. it makes rendering more deterministic by using simpler CPU renderer instead of OS GPU renderer  bug: https://groups.google.com/a/chromium.org/g/chromium-dev/c/8eR2GctzGuw
    // // '--disable-software-rasterizer',               <- DO NOT USE, harmless, used in tandem with --disable-gpu
    // // '--run-all-compositor-stages-before-draw',     <- DO NOT USE, makes headful chrome hang on startup (tested v121 Google Chrome.app on macOS)
    // // '--disable-gl-drawing-for-tests',              <- DO NOT USE, disables gl output (makes tests run faster if you dont care about canvas)
    // // '--blink-settings=imagesEnabled=false',        <- DO NOT USE, disables images entirely (only sometimes useful to speed up loading)

    // Process management & performance tuning
    // chrome://process-internals
    '--disable-lazy-loading',                         // make rendering more deterministic by loading all content up-front instead of on-focus
    '--disable-renderer-backgrounding',               // dont throttle tab rendering based on focus/visibility
    '--disable-background-networking',                // dont throttle tab networking based on focus/visibility
    '--disable-background-timer-throttling',          // dont throttle tab timers based on focus/visibility
    '--disable-backgrounding-occluded-windows',       // dont throttle tab window based on focus/visibility
    '--disable-ipc-flooding-protection',              // dont throttle ipc traffic or accessing big request/response/buffer/etc. objects will fail
    '--disable-extensions-http-throttling',           // dont throttle http traffic based on runtime heuristics
    '--disable-field-trial-config',                   // disable shared field trial state between browser processes 
    '--disable-back-forward-cache',                   // disable browsing navigation cache
    // '--in-process-gpu',                            <- DONT USE THIS, makes headful startup time ~5-10s slower (tested v121 Google Chrome.app on macOS)
    // '--disable-component-extensions-with-background-pages',  // TODO: check this, disables chrome components that only run in background (could lower startup time)

    // uncomment to disable hardware camera/mic/speaker access + present fake devices to websites
    // (faster to disable, but disabling breaks recording browser audio in puppeteer-stream screenrecordings)
    // '--use-fake-device-for-media-stream',
    // '--use-fake-ui-for-media-stream',
    // '--disable-features=GlobalMediaControls,MediaRouter,DialMediaRouteProvider',
    
    // // Output format options (PDF, screenshot, etc.)
    '--export-tagged-pdf',                            // include table on contents and tags in printed PDFs
    '--generate-pdf-document-outline',

    // Suppress first-run features, popups, hints, updates, etc.
    // chrome://system
    '--no-pings',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-default-apps',
    '--ash-no-nudges',
    '--disable-infobars',
    '--disable-search-engine-choice-screen',
    '--disable-session-crashed-bubble',
    '--simulate-outdated-no-au="Tue, 31 Dec 2099 23:59:59 GMT"',
    '--hide-crash-restore-bubble',
    '--suppress-message-center-popups',
    '--disable-client-side-phishing-detection',
    '--disable-domain-reliability',
    '--disable-component-update',
    '--disable-datasaver-prompt',
    '--disable-hang-monitor',
    '--disable-session-crashed-bubble',
    '--disable-speech-synthesis-api',
    '--disable-speech-api',
    '--disable-print-preview',
    '--safebrowsing-disable-auto-update',
    '--deny-permission-prompts',
    '--disable-external-intent-requests',
    '--disable-notifications',
    '--disable-desktop-notifications',
    '--noerrdialogs',
    '--disable-popup-blocking',
    '--disable-prompt-on-repost',
    '--silent-debugger-extension-api',
    '--block-new-web-contents',
    '--metrics-recording-only',
    '--disable-breakpad',

    
    // other feature flags
    // chrome://flags        chrome://components
    `--disable-features=${CHROME_DISABLED_COMPONENTS.join(',')}`,
    '--enable-features=NetworkService',
]
const CHROME_ARGS_EXTRA = []


const CHROME_LAUNCH_OPTIONS = {
    CHROME_PROFILE_PATH,
    CHROME_PROFILE_USER,
    CHROME_EXTENSIONS,
    CHROME_DEBUG_PORT,
    CHROME_DISABLED_COMPONENTS,
    DEFAULT_VIEWPORT,
    CHROME_ARGS_DEFAULT,
    CHROME_ARGS_EXTRA,
}
/* Chrome CLI Args Documentation
   - https://github.com/GoogleChrome/chrome-launcher/blob/main/docs/chrome-flags-for-tools.md
   - https://chromium.googlesource.com/chromium/chromium/+/master/content/public/common/content_switches.cc
   - https://jtway.co/optimize-your-chrome-options-for-testing-to-get-x1-25-impact-4f19f071bf45
   - https://peter.sh/experiments/chromium-command-line-switches/
   - https://www.chromium.org/developers/how-tos/run-chromium-with-flags/
   - https://github.com/manoj9788/Chrome-Driver-arguments/blob/master/README.md
*/
const getChromeArgs = ({CHROME_ARGS_DEFAULT, CHROME_ARGS_EXTRA,
                        CHROME_PROFILE_PATH, CHROME_PROFILE_USER,
                        CHROME_EXTENSIONS,
                        CHROME_DEBUG_PORT,
                        CHROME_DISABLED_COMPONENTS,
                        DEFAULT_VIEWPORT}=CHROME_LAUNCH_OPTIONS) =>
    [
        ...CHROME_ARGS_DEFAULT,
        `--user-data-dir=${CHROME_PROFILE_PATH}`,
        `--profile-directory=${CHROME_PROFILE_USER}`,
        `--load-extension=${CHROME_EXTENSIONS.map(({unpacked_path}) => unpacked_path).join(',')}`,
        `--allowlisted-extension-id=${CHROME_EXTENSIONS.map(({id}) => id).join(',')}`,
        `--window-size=${DEFAULT_VIEWPORT.width},${DEFAULT_VIEWPORT.height}`,
        `--remote-debugging-port=${CHROME_DEBUG_PORT}`,
        `--disable-features=${CHROME_DISABLED_COMPONENTS.join(',')}`,
        ...CHROME_ARGS_EXTRA,
    ]


/******************** Chrome Extension Management *****************************/

function getExtensionId(unpacked_path) {
    const manifest_path = path.join(unpacked_path, 'manifest.json')
    if (!fs.existsSync(manifest_path)) return null

    // chrome uses a SHA256 hash of the unpacked extension directory path to compute a dynamic id
    const hash = crypto.createHash('sha256');
    hash.update(Buffer.from(unpacked_path, 'utf-8'));
    const detected_extension_id = Array.from(hash.digest('hex'))
      .slice(0, 32) // Convert each hexadecimal character to a character in the range 'a'-'p'
      .map(i => String.fromCharCode(parseInt(i, 16) + 'a'.charCodeAt(0)))
      .join('');

    return detected_extension_id
}

async function installExtension(extension) {
    const manifest_path = path.join(extension.unpacked_path, 'manifest.json')

    // Download extensions using:
    // curl -fsSL 'https://clients2.google.com/service/update2/crx?response=redirect&prodversion=1230&acceptformat=crx3&x=id%3D$EXTENSION_ID%26uc' > extensionname.crx
    // unzip -d extensionname extensionname.zip

    if (!fs.existsSync(manifest_path) && !fs.existsSync(extension.crx_path)) {
        console.log("[🛠️] Downloading missing extension", extension.name, extension.webstore_id, '->', extension.crx_path);

        // Download crx file from ext.crx_url -> ext.crx_path
        const response = await fetch(extension.crx_url) as Response
        const crx_file = fs.createWriteStream(extension.crx_path);
        if (response.headers.get("content-length") && response.body) {
            // @ts-ignore
            const crx_stream = Readable.fromWeb(response.body)
            await finished(crx_stream.pipe(crx_file))
        } else {
            console.warn('[⚠️] Failed to download extension', extension.name, extension.webstore_id)
        }
    }
    
    var {stdout, stderr} = {stdout: '', stderr: ''}

    // Unzip crx file from ext.crx_url -> ext.unpacked_path
    await fs.promises.mkdir(extension.unpacked_path, {recursive: true})
    try {
        var {stdout, stderr} = await exec(`/usr/bin/unzip ${extension.crx_path} -d ${extension.unpacked_path}`)
    } catch(err1) {
        try {
            await unzip(extension.crx_path, extension.unpacked_path)
        } catch(err2) {
            // console.error(`[❌] Failed to install ${extension.crx_path}: could not unzip crx`, err1, err2)
            // return false
        }
    }

    if (!fs.existsSync(manifest_path))
        console.error(`[❌] Failed to install ${extension.crx_path}: could not find manifest.json in unpacked_path`, stdout, stderr)

    return fs.existsSync(manifest_path)
}

async function loadOrInstallExtension(ext) {
    if (!(ext.webstore_id || ext.unpacked_path))
        throw 'Extension must have either {webstore_id} or {unpacked_path}'

    // Set statically computable extension metadata
    ext.webstore_id =       ext.webstore_id     || ext.id
    ext.name =              ext.name            || ext.webstore_id
    ext.webstore_url =      ext.webstore_url    || `https://chromewebstore.google.com/detail/${ext.webstore_id}`
    ext.crx_url =           ext.crx_url         || `https://clients2.google.com/service/update2/crx?response=redirect&prodversion=1230&acceptformat=crx3&x=id%3D${ext.webstore_id}%26uc`
    ext.crx_path =          ext.crx_path        || path.join(CHROME_EXTENSIONS_DIR, `${ext.webstore_id}__${ext.name}.crx`)
    ext.unpacked_path =     ext.unpacked_path   || path.join(CHROME_EXTENSIONS_DIR, `${ext.webstore_id}__${ext.name}`)
    
    const manifest_path =   path.join(ext.unpacked_path, 'manifest.json')
    ext.read_manifest =     () => JSON.parse(fs.readFileSync(manifest_path, 'utf-8'))
    ext.read_version =      () => fs.existsSync(manifest_path) && ext.read_manifest()?.version || null

    // if extension is not installed, download and unpack it
    if (!ext.read_version()) {
        await installExtension(ext)
    }

    // autodetect id from filesystem path (unpacked extensions dont have stable IDs)
    ext.id = getExtensionId(ext.unpacked_path)
    ext.version = ext.read_version()
    if (!ext.version) {
        console.warn('[❌] Unable to detect ID and version of installed extension', prettyPath(ext.unpacked_path))
    } else {
        console.log(`[➕] Installed extension ${ext.name} (${ext.version})...`.padEnd(82), prettyPath(ext.unpacked_path))
    }

    return ext
}

async function isTargetExtension(target) {
    let target_type
    let target_ctx
    let target_url
    try {
        target_type = target.type()
        target_ctx = (await target.worker()) || (await target.page()) || null
        target_url = target.url() || target_ctx?.url() || null
    } catch(err) {
        if (String(err).includes('No target with given id found')) {
            // because this runs on initial browser startup, we sometimes race with closing the initial
            // new tab page. it will throw a harmless error if we try to check a target that's already closed,
            // ignore it and return null since that page is definitely not an extension's bg page anyway
            target_type = 'closed'
            target_ctx = null
            target_url = 'about:closed'
        } else {
            throw err
        }
    }
    
    const target_is_bg = ['service_worker', 'background_page'].includes(target_type)
    const target_is_extension = target_url?.startsWith('chrome-extension://')
    const extension_id = (target_is_extension && target_url.split('://')[1].split('/')[0]) || null
    const manifest_version = target_type === 'service_worker' ? '3' : '2'

    return {
        target_type,
        target_ctx,
        target_url,
        target_is_bg,
        target_is_extension,
        extension_id,
        manifest_version,
    }
}

async function loadExtensionFromTarget(extensions, target) {
    const {
        target_is_bg,
        target_is_extension,
        target_type,
        target_ctx,
        target_url,
        extension_id,
        manifest_version,
    } = await isTargetExtension(target)
    
    if (!(target_is_bg && extension_id && target_ctx))
        return null

    const manifest = await target_ctx.evaluate(() =>
        // @ts-ignore
        chrome.runtime.getManifest())
    
    const { name, version, homepage_url, options_page, options_ui } = manifest

    if (!version || !extension_id)
        return null
    
    const options_url = await target_ctx.evaluate(
        (options_page) => chrome.runtime.getURL(options_page),
        options_page || options_ui?.page || 'options.html',
    )
    
    const commands = await target_ctx.evaluate(async () =>
        (await new Promise((resolve, reject) => {
            if (chrome.commands)
                chrome.commands.getAll(resolve)
            else
                resolve({})
        }))
    )

    // console.log(`[+] Found Manifest V${manifest_version} Extension:`, extension_id, name, target_url, Object.keys(commands).length)

    let dispatchEval = async (...args) =>
        await target_ctx.evaluate(...args)
    let dispatchPopup = async () =>
        await target_ctx.evaluate('chrome.action?.openPopup() || chrome.tabs.create({url: chrome.runtime.getURL("popup.html")})')
    
    let dispatchAction
    let dispatchMessage
    let dispatchCommand

    if (manifest_version === '3') {
        dispatchAction = async (tab) => {
            // https://developer.chrome.com/docs/extensions/reference/api/action#event-onClicked
            return await target_ctx.evaluate(async (tab) => {
                tab = tab || (await new Promise((resolve) =>
                    chrome.tabs.query({currentWindow: true, active: true}, ([tab]) => resolve(tab))))
                // @ts-ignore
                return await chrome.action.onClicked.dispatch(tab)
            }, tab)
        }
        dispatchMessage = async (message, options) => {
            // https://developer.chrome.com/docs/extensions/reference/api/runtime
            return await target_ctx.evaluate(async (extension_id, message, options) => {
                return await chrome.runtime.sendMessage(extension_id, message, options)
            }, extension_id, message, options)
        }
        dispatchCommand = async (command, tab) => {
            // https://developer.chrome.com/docs/extensions/reference/api/commands#event-onCommand
            return await target_ctx.evaluate(async (command, tab) => {
                // @ts-ignore
                return await chrome.commands.onCommand.dispatch(command, tab)
            }, command, tab)
        }
    } else if (manifest_version === '2') {
        dispatchAction = async (tab) => {
            // https://developer.chrome.com/docs/extensions/mv2/reference/browserAction#event-onClicked
            return await target_ctx.evaluate(async (tab) => {
                tab = tab || (await new Promise((resolve) =>
                    chrome.tabs.query({currentWindow: true, active: true}, ([tab]) => resolve(tab))))
                // @ts-ignore
                return await chrome.browserAction.onClicked.dispatch(tab)
            }, tab)
        }
        dispatchMessage = async (message, options) => {
            // https://developer.chrome.com/docs/extensions/mv2/reference/runtime#method-sendMessage
            return await target_ctx.evaluate(async (extension_id, message, options) => {
                return await new Promise((resolve) =>
                    chrome.runtime.sendMessage(extension_id, message, options, resolve)
                )
            }, extension_id, message, options)
        }
        dispatchCommand = async (command, tab) => {
            // https://developer.chrome.com/docs/extensions/mv2/reference/commands#event-onCommand
            return await target_ctx.evaluate(async (command, tab) => {
                return await new Promise((resolve) =>
                    // @ts-ignore
                    chrome.commands.onCommand.dispatch(command, tab, resolve)
                )
            }, command, tab)
        }
    }
    const existing_extension = extensions.filter(({id}) => id === extension_id)[0] || {}

    const new_extension = {
        ...existing_extension,
        id: extension_id,
        webstore_name: name,

        target,
        target_ctx,
        target_type,
        target_url,

        manifest_version,
        manifest,
        version,
        homepage_url,
        options_url,

        dispatchEval,         // run some JS in the extension's service worker context
        dispatchPopup,        // open the extension popup
        dispatchAction,       // trigger an extension menubar icon click
        dispatchMessage,      // send a chrome runtime message in the service worker context
        dispatchCommand,      // trigger an extension keyboard shortcut command
    }

    console.log(`[➕] Loaded extension ${name.substring(0, 32)} (${version}) ${target_type}...`.padEnd(82), target_url)
    Object.assign(existing_extension, new_extension)

    return new_extension
}



async function getChromeExtensionsFromPersona({CHROME_EXTENSIONS, CHROME_EXTENSIONS_DIR}) {
    console.log('*************************************************************************')
    console.log(`[⚙️] Installing ${CHROME_EXTENSIONS.length} chrome extensions from CHROME_EXTENSIONS...`)
    try {
        // read extension metadata from filesystem (installing from Chrome webstore if extension is missing)
        for (const extension of CHROME_EXTENSIONS) {
            Object.assign(extension, await loadOrInstallExtension(extension))
        }

        // for easier debugging, write parsed extension info to filesystem
        await overwriteFile(
            CHROME_EXTENSIONS_JSON_PATH.replace('.json', '.present.json'),
            CHROME_EXTENSIONS,
        )
    } catch(err) {
        console.error(err)
    }
    console.log('*************************************************************************')
    return CHROME_EXTENSIONS
}

let _EXTENSIONS_CACHE = null
async function getChromeExtensionsFromCache({browser, extensions=CHROME_EXTENSIONS, extensions_dir=CHROME_EXTENSIONS_DIR}) {
    if (_EXTENSIONS_CACHE === null) {
        console.log(`[⚙️] Loading ${CHROME_EXTENSIONS.length} chrome extensions from CHROME_EXTENSIONS...`)

        // find loaded Extensions at runtime / browser launch time & connect handlers
        // looks at all the open targets for extension service workers / bg pages
        for (const target of browser.targets()) {
            // mutates extensions object in-place to add metadata loaded from filesystem persona dir
            await loadExtensionFromTarget(extensions, target)
        }
        _EXTENSIONS_CACHE = extensions

        // write installed extension metadata to filesystem extensions.json for easier debugging
        await overwriteFile(
            CHROME_EXTENSIONS_JSON_PATH.replace('.json', '.loaded.json'),
            extensions,
        )
        await overwriteSymlink(
            CHROME_EXTENSIONS_JSON_PATH.replace('.json', '.loaded.json'),
            CHROME_EXTENSIONS_JSON_PATH,
        )
    }
    
    return _EXTENSIONS_CACHE
}

async function setup2CaptchaExtension({browser, extensions}) {
    let page = null
    try {
        // open a new tab to finish setting up the 2captcha extension manually using its extension options page
        page = await browser.newPage()
        const { options_url } = extensions.filter(ext => ext.name === 'captcha2')[0]
        await page.goto(options_url)
        await wait(2_500)
        await page.bringToFront()
    
        // type in the API key and click the Login button (and auto-close success modal after it pops up)
        await page.evaluate(() => {
            const elem = document.querySelector("input[name=apiKey]") as HTMLInputElement
            elem.value = ""
        })
        await page.type('input[name=apiKey]', API_KEY_2CAPTCHA, { delay: 25 })
        
        // toggle all the important switches to ON
        await page.evaluate(() => {
            const checkboxes = Array.from(document.querySelectorAll<HTMLInputElement>('input#isPluginEnabled, input[name*=enabledFor], input[name*=autoSolve]'));
            for (const checkbox of checkboxes) {
                if (!checkbox.checked) checkbox.click()
            }
        })
    
        let dialog_opened = false
        page.on('dialog', async (dialog) => {
            setTimeout(async () => {
                await dialog.accept();
                dialog_opened = true
            }, 500);
        })
        await page.click('button#connect')
        await wait(2_500)
        if (!dialog_opened) {
            throw `2captcha extension login confirmation dialog never opened, please check its options page manually: ${options_url}`
        }
        console.log('[🔑] Configured the 2captcha extension using its options page...')
    } catch(err) {
        console.warn(`[❌] Failed to configure the 2captcha extension using its options page!`, err)
    }
    if (page) await page.close()
}

async function speedtest({browser, page, measureUpload=true, timeout=25000}: {browser?: Browser, page?: Page, measureUpload?: boolean, timeout?: number}) {
    // run a speedtest using fast.com, printing results once per second

    browser = browser || await page.browser()
    page = page || await browser.newPage()

    // save one speedtest_<date>.json result per day
    const today = versionStrFromDate(new Date(), {withDate: true, withTime: false})
    const SPEEDTEST_PATH = path.join(SPEEDTESTS_DIR, `speedtest_${today}.json`)

    // check if we've already run one today, if so return earlier results and skip running again
    try {
        return JSON.parse(await fs.promises.readFile(SPEEDTEST_PATH, 'utf-8'))
    } catch(err) {
        // otherwise speedtest does not exist yet for today, continue onwards...
    }

    console.log('[🚤] Running Speedtest using Fast.com...'.padEnd(82), prettyPath(SPEEDTEST_PATH))

    await page.goto('https://fast.com', {timeout, waitUntil: 'domcontentloaded'});
    await page.waitForSelector('#speed-value', {timeout})

    let result = null
    let loop_idx = 0

    while (loop_idx < 100) {
        result = await page.evaluate(() => {
            const $ = document.querySelector.bind(document);

            return {
                downloadSpeed: Number($('#speed-value').textContent),
                downloadUnit: $('#speed-units').textContent.trim(),
                downloaded: Number($('#down-mb-value').textContent.trim()),
                uploadSpeed: Number($('#upload-value').textContent),
                uploadUnit: $('#upload-units').textContent.trim(),
                uploaded: Number($('#up-mb-value').textContent.trim()),
                latency: Number($('#latency-value').textContent.trim()),
                bufferBloat: Number($('#bufferbloat-value').textContent.trim()),
                userLocation: $('#user-location').textContent.trim(),
                userIp: $('#user-ip').textContent.trim(),
                isDone: Boolean($('#speed-value.succeeded') && $('#upload-value.succeeded')),
            };
        })
        if (result.downloadSpeed > 0) {
            // console.log(JSON.stringify(result).replaceAll('"', '').replaceAll(',', ' ').replaceAll('{', '').replaceAll('}', ''))
        }

        if (result.isDone || (!measureUpload && result.uploadSpeed)) {
            break
        }

        await wait(500)
        loop_idx++
    }

    await Promise.allSettled([
        page.close(),
        overwriteFile(SPEEDTEST_PATH, result)
    ])

    return result
}

/******************************************************************************/
/******************************************************************************/

const ALREADY_ARCHIVED = new Set(['', 'about:blank', 'chrome://newtab', 'chrome://version'])
const TASKS_PER_RUN_LIMIT = 200

async function botArchiveTask({page, data, url=''}) {
    url = url || data  // puppeteer-cluster passes in the url value via the data: arg

    const is_unarchivable_url = URL_SCHEMES_IGNORED.includes(url.split(':')[0])
    const is_already_archived = ALREADY_ARCHIVED.has(url.slice(0, 4096))
    if (is_unarchivable_url || is_already_archived) return null 
    ALREADY_ARCHIVED.add(url.slice(0, 4096))

    if (ALREADY_ARCHIVED.size > TASKS_PER_RUN_LIMIT) {
        console.warn('[❌] Hit maximum URLs archived per browser session, exiting to free memory.')
        console.warn('     Run this process again to continue with the next batch...')
        process.exit(21)
    }

    const browser = await page.browser()
    const client = await page.target().createCDPSession()
    const extensions = await getChromeExtensionsFromCache({browser})
    const browser_version = await browser.version()
    const original_url = url.toString()
    const start_time = (new Date())
    
    console.log('[0/4]-------------------------------------------------------------------------')
    const snapshot_dir = await setupSnapshotDir({original_url, start_time})
    const snapshot = await setupSnapshotDB({original_url, start_time, snapshot_dir})
    console.log('[1/4]-------------------------------------------------------------------------')
    console.log(`[🪟] Starting page & viewport setup (${browser_version} ${DEFAULT_VIEWPORT.isMobile ? 'mobile' : 'desktop'} ${DEFAULT_VIEWPORT.width}x${DEFAULT_VIEWPORT.height}px)...`)


    const page_state = {
        // global static state
        browser,
        client,
        browser_version,
        extensions,

        // per-page static metadata
        original_url,
        snapshot,
        snapshot_dir,
        start_time: start_time.toISOString(),
        start_ts: Number(start_time),
        version: versionStrFromDate(start_time),

        // per-page mutable archiving state
        main_response: null,
        recorder: null,
        console_log: [],
        traffic_log: {},
        redirects: {},
    }
    page._original_url = original_url
    
    try {
        // run all page setup functions in parallel
        const results = await Promise.allSettled([
            // loadAuthStorage(page, page_state, { apply: true }),
            startMetadataRecording(page, page_state),
            setupURLRewriting(page, page_state),
            // setupViewport(page, page_state),
            setupModalAutoClosing(page, page_state),
            loadCloudflareCookie(page, page_state),
            startResponseSaving(page, page_state),
            saveYTDLP(page, page_state),
            saveGALLERYDL(page, page_state),
            // saveSourceMaps(page, page_state),
            // TODO: someday setup https://github.com/osnr/TabFS ?
        ]);
        // run all page setup functions in parallel
        const rejected = results
            .filter(result => result.status === 'rejected')
            .map(result => (result as PromiseRejectedResult).reason);
        if (rejected.length) console.warn('[⚠️] Partial failures during page setup:', rejected);
    } catch(err) {
        console.error('[❌] PAGE SETUP ERROR', JSON.stringify(err, null, 4))
        return
    }


    console.log('[2/4]-------------------------------------------------------------------------')

    console.log('[➡️] NAVIGATION[INI]', ANSI.blue + url + ANSI.reset)
    const startrecording_promise = startScreenrecording(page, page_state)
    page_state.main_response = await page.goto(url, {waitUntil: 'load', timeout: 40_000})
    try {
        const results = await Promise.allSettled([
            startrecording_promise,
            page.bringToFront(),
            page.waitForNetworkIdle({concurrency: 0, idleTime: 900, timeout: 20_000}),
        ])
        const rejected = results
            .filter(result => result.status === 'rejected')
            .map(result =>  (result as PromiseRejectedResult).reason)
        if (rejected.length) console.warn('[⚠️] Parial failures during page load:', rejected)
    } catch(err) {
        console.error('[❌] ERROR DURING PAGE LOAD', JSON.stringify(err, null, 4))
        return
    }

    if (page_state.main_response === null) {
        page_state.main_response = await page.waitForResponse(() => true)
    }
    assert(page_state.main_response)
    if (page_state.main_response.status() == 429) {
        throw `[⚠️] Got 429 rate-limit response, skipping this URL for now...`
    }

    // emulate human browsing behavior
    // await disableAnimations(page, page_state);
    await jiggleMouse(page, page_state);
    await solveCaptchas(page, page_state);
    await blockRedirects(page, page_state);
    await scrollDown(page, page_state);
    // await expandComments(page, page_state);
    await submitForm(page, page_state);
    // await blockJSExecution(page, page_state);

    console.log('[3/4]-------------------------------------------------------------------------')
    
    // stop tampering with page requests & JS / recording metadata / traffic log
    await stopMetadataRecording(page, page_state)

    // do all synchonous archiving steps that need exclusive use of the whole page while doing stuff
    const saveScreenrecording_promise = saveScreenrecording(page, page_state);
    await saveScreenshot(page, page_state);
    await savePDF(page, page_state);

    console.log('[4/4]-------------------------------------------------------------------------')

    // do all async archiving steps that can be run at the same time
    await inlineShadowDOM(page, page_state);
    const results = await Promise.allSettled([
        saveTitle(page, page_state),
        saveSEO(page, page_state),
        saveFavicon(page, page_state),
        saveSSL(page, page_state),
        saveRequests(page, page_state),
        saveRedirects(page, page_state),
        saveHeaders(page, page_state),
        saveRaw(page, page_state),
        saveDOM(page, page_state),
        saveBodyText(page, page_state),
        // savePandoc(page, page_state),
        saveReadability(page, page_state),
        saveAccessibility(page, page_state),
        saveOutlinks(page, page_state),
        // saveAuthStorage(page, page_state),
        saveAIQualityAssuranceResult(page, page_state),
    ]);

    // do all sync archiving steps that require browser extensions at the very end (they are the buggiest)
    const bg_results = Promise.allSettled([
        saveScreenrecording_promise,
        saveSinglefile(page, page_state),
        // saveArchiveWebPage(page, page_state),
        // savePocket(page, page_state),
    ])

    const {duration} = await saveMetrics(page, page_state);

    const rejected = results
        .filter(result => result.status === 'rejected')
        .map(result =>  (result as PromiseRejectedResult).reason)                            // not sure why this has a ts-error, .reason does exist on rejected promises

    if (rejected.length)
        console.warn('[⚠️] Parial failures during archiving:', rejected)

    // Start an interactive REPL here with the `page` instance.
    // https://github.com/berstend/puppeteer-extra/tree/master/packages/puppeteer-extra-plugin-repl
    // await page.repl()
    // await page.browser().repl()

    console.log(`[✅] ${ANSI.blue}Finished archiving in ${duration/1000}s.${ANSI.reset}`)
    
    try {
        const rejected = (await bg_results)
            .filter(result => result.status === 'rejected')
            .map(result =>  (result as PromiseRejectedResult).reason)                        // not sure why this has a ts-error, .reason does exist on rejected promises
        if (rejected.length)
            console.warn('[⚠️] Parial failures during wrap-up tasks:', rejected)
        
        console.log('[🗑️] Resetting to about:blank to ensure memory is freed...')
        await page.goto('about:blank')
        await page.close()
    } catch(err) {
        console.log(err)
    }

    // symlink the best results from across all the versions/ into the snapshot dir root
    await symlinkBestSnapshotResults(snapshot_dir)

    // display latest version screenshot GIF
    console.log()
    try {
        const latest_version_gif = path.join(snapshot_dir, 'versions', page_state.version, path.basename(SCREENRECORDGIF_PATH(page)))
        const dirent = await blockUntilExists(latest_version_gif, {min_bytes: 100, timeout: 15_000})
        child_process.spawn('/Users/squash/.iterm2/imgcat', [dirent.abspath], {stdio: [null, 'inherit', 'inherit']})
    } catch(err) {
        console.warn('[⚠️] Failed to display screenrecording.gif...', err)
        console.log()
    }

    // determine whether task succeeded or failed based on AI QA score
    const latest_version_aiqa = path.join(snapshot_dir, 'versions', page_state.version, path.basename(AIQA_PATH(page)))
    const qa_results = JSON.parse((await fs.promises.readFile(latest_version_aiqa)).toString())
    if (qa_results.pct_visible < 50) {
        throw `[❌] Task completed with problems, got AI QA score of ${qa_results.pct_visible}%! ${qa_results.warnings.join(', ')} ${qa_results.error_text || ''}`
    } else {
        console.log(`[💫] Task completed succesfully: ${qa_results.pct_visible}%    ${qa_results.warnings.join(', ') || ''}`)
        console.log(`     Summary: ${(qa_results.main_content_title || qa_results.description || 'No title/description detected').substring(0, 80)}... ${qa_results.main_content_author || ''} ${qa_results.main_content_date || ''}`)
        return true
    }
}

async function passiveArchiveTask({browser, page, url}) {
    // archive passively (e.g. a tab that was opened already by a human), without changing the active page

    const is_unarchivable_url = URL_SCHEMES_IGNORED.includes(url.split(':')[0])
    const is_already_archived = ALREADY_ARCHIVED.has(url.slice(0, 4096))
    if (is_unarchivable_url || is_already_archived) return null
    ALREADY_ARCHIVED.add(url.slice(0, 4096))

    // these have to be as early as possible because we're racing with the page load (we might even be too late)
    // jk nevermind, we now re-open a new bg tab for every tab that's created to re-capture the initial request
    // await page.setRequestInterception(true);
    // await page.setCacheEnabled(false);

    const original_url = url.toString()
    const start_time = (new Date())
    const browser_version = await browser.version()
    
    console.log('------------------------------------------------------------------------------')
    console.log('[➕] Starting archive of new tab opened in driver browser...', await browser.version())
    const snapshot_dir = await setupSnapshotDir({original_url, start_time})
    const snapshot = await setupSnapshotDB({ original_url, start_time, snapshot_dir })
    console.log('------------------------------------------------------------------------------')
    console.log(`[🪟] Starting page & viewport setup (${browser_version} ${DEFAULT_VIEWPORT.isMobile ? 'mobile' : 'desktop'} ${DEFAULT_VIEWPORT.width}x${DEFAULT_VIEWPORT.height}px)...`)

    // create a new page in the background for archiving
    const old_page = page
    page = await browser.newPage()
    await old_page.bringToFront()
    const client = await page.target().createCDPSession()
    const extensions = await getChromeExtensionsFromCache({ browser })

    const page_state = {
        // global static state
        browser,
        client,
        browser_version,
        extensions,

        // per-page static metadata
        original_url,
        snapshot,
        snapshot_dir,
        start_time: start_time.toISOString(),
        start_ts: Number(start_time),
        version: versionStrFromDate(start_time),

        // per-page mutable archiving state
        main_response: null,
        recorder: null,
        console_log: [],
        traffic_log: {},
        redirects: {},
    }
    page._original_url = original_url

    try {
        
        // run all page setup functions in parallel
        const results = await Promise.allSettled([
            // loadAuthStorage(page, page_state, {apply: true}),
            startMetadataRecording(page, page_state),
            setupURLRewriting(page, page_state),
            startResponseSaving(page, page_state),
            saveYTDLP(page, page_state),
            saveGALLERYDL(page, page_state),
            // saveSourceMaps(page, page_state),
        ]);
        const rejected = results
            .filter(result => result.status === 'rejected')
            .map(result =>  (result as PromiseRejectedResult).reason)
        if (rejected.length) console.warn('[⚠️] Parial failures during page setup:', rejected)
    } catch(err) {
        console.warn('[❌] ERROR DURING PAGE SETUP', JSON.stringify(err, null, 4))
        return
    }

    // load the url in the background page, then switch to it once its loaded and close the original tab
    console.log('[➡️] NAVIGATION[INI]', ANSI.blue + url + ANSI.reset)
    const startrecording_promise = startScreenrecording(page, page_state)
    page_state.main_response = await page.goto(url, {waitUntil: 'load', timeout: 40_000})
    
    // for debugging
    globalThis.page = page
    globalThis.page_state = page_state

    // start loading the page, start screenrecording, close the old page, and wait for loading to finish (all at once, fine for these to race)
    try {
        const results = await Promise.allSettled([
            startrecording_promise,
            page.bringToFront(),
            old_page.close(),
            page.waitForNetworkIdle({concurrency: 0, idleTime: 900, timeout: 20_000}),
        ])
        const rejected = results
            .filter(result => result.status === 'rejected')
            .map(result =>  (result as PromiseRejectedResult).reason)
        if (rejected.length) console.warn('[⚠️] Parial failures during [age load:', rejected)
    } catch(err) {
        console.warn('[❌] ERROR DURING PAGE LOAD', JSON.stringify(err, null, 4))
        return
    }

    if (page_state.main_response === null) {
        page_state.main_response = await page.waitForResponse(() => true)
    }
    assert(page_state.main_response)
    if (page_state.main_response.status() == 429) {
        throw `[⚠️] Got 429 rate-limit response, skipping this URL for now...`
    }

    // resume page if paused by waitForDebuggerOnStart/dev tools debugger/backgrounding
    try {
        await client.send('Page.enable');
        await client.send('Page.setWebLifecycleState', {state: 'active'});
        await client.send('Runtime.runIfWaitingForDebugger')
    } catch(err) { /* console.warn(err) */ }

    // wait a couple seconds for page to finish loading
    await wait(5_000)

    // emulate human browsing behavior
    // await disableAnimations(page, page_state);
    // await jiggleMouse(page, page_state);
    await solveCaptchas(page, page_state);
    // await blockRedirects(page, page_state);
    // await scrollDown(page, page_state);
    // await expandComments(page, page_state);
    await submitForm(page, page_state);
    // await blockJSExecution(page, page_state);
    await stopMetadataRecording(page, page_state)   // stop tampering with page requests & JS

    console.log('[3/4]-------------------------------------------------------------------------')

    // do all synchonous archiving steps that need exclusive use of the whole page while doing stuff
    const saveScreenrecording_promise = saveScreenrecording(page, page_state);
    await saveScreenshot(page, page_state);
    await savePDF(page, page_state);

    console.log('[4/4]-------------------------------------------------------------------------')

    // do all async archiving steps that can be run at the same time
    await inlineShadowDOM(page, page_state);
    const results = await Promise.allSettled([
        saveTitle(page, page_state),
        saveSEO(page, page_state),
        saveFavicon(page, page_state),
        saveSSL(page, page_state),
        saveRequests(page, page_state),
        saveRedirects(page, page_state),
        saveHeaders(page, page_state),
        saveRaw(page, page_state),
        saveDOM(page, page_state),
        saveBodyText(page, page_state),
        // savePandoc(page, page_state),
        saveReadability(page, page_state),
        saveAccessibility(page, page_state),
        saveOutlinks(page, page_state),
        // saveAuthStorage(page, page_state),
        saveAIQualityAssuranceResult(page, page_state),
    ]);

    // do all sync archiving steps that require browser extensions at the very end (they are the buggiest)
    const bg_results = Promise.allSettled([
        saveScreenrecording_promise,
        saveSinglefile(page, page_state),
        // saveArchiveWebPage(page, page_state),
        // savePocket(page, page_state),
    ])

    const {duration} = await saveMetrics(page, page_state);

    const rejected = results
        .filter(result => result.status === 'rejected')
        .map(result =>  (result as PromiseRejectedResult).reason)

    if (rejected.length)
        console.warn('[⚠️] Parial failures during page archiving:', rejected)

    // Start an interactive REPL here with the `page` instance.
    // https://github.com/berstend/puppeteer-extra/tree/master/packages/puppeteer-extra-plugin-repl
    // await page.repl()
    // await page.browser().repl()

    console.log(`[✅] Finished archiving in ${duration/1000}s.`,)
    
    // await page.tracing.stop();
    try {
        const rejected = (await bg_results)
            .filter(result => result.status === 'rejected')
            .map(result =>  (result as PromiseRejectedResult).reason)
        if (rejected.length)
            console.warn('[⚠️] Parial failures during page wrap-up tasks:', rejected)
    } catch(err) {
        console.log(err)
    }
    await symlinkBestSnapshotResults(snapshot_dir)
}


/******************************************************************************/
/************************* Page Setup Tasks ***********************************/



async function setupSnapshotDir({original_url, start_time, snapshot_dir=null}) {
    // setup archive/<id> snapshot output folder, move old files into versions/<date>/* + clear any existing symlinks

    const snap_dir = snapshot_dir || TASK_PATH(original_url)
    
    console.log()
    console.log()
    console.log(ANSI.blue + original_url + ANSI.reset)
    console.log(ANSI.black + snap_dir + ANSI.reset)
    console.log()
    console.log('[📂] Setting up Snapshot output directory...'.padEnd(82), prettyPath(snap_dir))

    // check for existing data at old legacy paths e.g. ./data/archive/1999999999.1723425
    const hacky_dir = path.join(ARCHIVE_DIR, `1999999999.${hashCode(original_url)}`)
    const known_dir = SNAPSHOT_DIRS_BY_URL[original_url]

    const known_dir_exists = fs.existsSync(known_dir)
    const hacky_dir_exists = fs.existsSync(hacky_dir)

    if (snap_dir == hacky_dir) {
        if (known_dir_exists) {
            throw `Tried to create snapshot in ${snap_dir} but potential duplicate exists in ${known_dir}!`
        }
    } else if (snap_dir == known_dir) {
        if (hacky_dir_exists) {
            throw `Tried to create snapshot in ${snap_dir} but potential duplicate exists in ${hacky_dir}!`
        }
    } else {
        if (known_dir_exists) {
            throw `Tried to create snapshot in ${snap_dir} but potential duplicate exists in ${known_dir}!`
        } else if (hacky_dir_exists) {
            throw `Tried to create snapshot in ${snap_dir} but potential duplicate exists in ${hacky_dir}!`
        } else {
            throw `Tried to create snapshot in ${snap_dir} but its not a recognized snapshot dir path:\n    - ${known_dir}\n    - ${hacky_dir}`
        }
    }
    
    // mkdir -p ./data/archive/<snap_id>/versions && cd ./data/archive/<snap_id>
    await fs.promises.mkdir(path.join(snap_dir, 'versions'), {recursive: true})
    process.chdir(snap_dir)

    // clear any /data/archive/<snap_id>/*.* symlinks pointing to existing ./versions/<versionid>/*.* files
    await clearSnapshotDirSymlinks(snap_dir)

    // move /data/archive/<snap_id>/*.* loose output files from any prior run into ./versions/<versionid>/*.*
    await collectSnapshotDirVersionFiles(snap_dir)    
    
    // update /data/indexes/<index_name>/* to include references to /data/archive/<snap_id> as-needed
    await updateSnapshotDirIndexes(snap_dir, {original_url, start_time})

    // assert /data/archive/<snap_id>/ contains no invalid/partial files + is empty/ready to receive new files
    await assertSnapshotDirIsValid(snap_dir, {is_empty: true})

    return snap_dir
}

// ./index/<index_name> : index_getter(page_state) => "<index_key_str>"
const INDEXES = {
    snapshots_by_day: ({start_time}) =>
        versionStrFromDate(start_time, {withDate: true, withTime: false}),
    snapshots_by_domain: ({original_url}) =>
        (new URL(original_url)).hostname || '',      // hostname does not include :port
}

async function updateSnapshotDirIndexes(snap_dir, page_state, indexes=INDEXES, indexes_dir=INDEXES_DIR) {
    assert(indexes)
    console.log(`[🔎] Linking Snapshot in indexes (${Object.keys(indexes).join(', ')})...`)
    // const {snapshot_dir, original_url, start_ts} = page_state
    for (const [index_name, index_key_getter] of Object.entries(indexes)) {
        const index_entry = await indexSnapshotDir(snap_dir, {index_name, index_key_getter, indexes_dir}, page_state)
    }
}

async function indexSnapshotDir(snap_dir, {index_name, index_key_getter, indexes_dir=INDEXES_DIR}, page_state) {
    // place symlinks to this snapshot in any /indexes/<index_name/ indexes as-needed
    // const snap_id = snap_dir.split('/').at(-1)

    const index_dir = path.join(indexes_dir, index_name)                         // /data/index/snapshots_by_day
    await fs.promises.mkdir(index_dir, {recursive: true})

    // calculate the index key, e.g. "200101231" or "example.com" 
    assert(index_name && index_key_getter)
    assert(page_state)
    const index_key = String(index_key_getter(page_state))                       // '20010131'
    assert(index_key)
    const snap_id = path.parse(snap_dir).base                                    // '19999999.23423523'
    assert(snap_id)

    const index_entries_dir = path.join(index_dir, index_key)                    // /data/index/snapshots_by_day/20010131
    await fs.promises.mkdir(index_entries_dir, {recursive: true})

    const symlink_path = path.join(index_entries_dir, snap_id)                   // /data/index/snapshots_by_day/20010131/19999999.23423523

    // create symlink index/snapshots_by_day/<YYYYMMDD>/<snap id> -> ./archive/<snap_id> symlink
    const {symlink_abspath} = await overwriteSymlink(snap_dir, symlink_path, {relative: true, mkdirs: false})
}


async function collectSnapshotDirVersionFiles(snap_dir) {
    // move archive/<id>/*.* snapshot output files into archive/<id>/versions/<date>/* dated version folder

    // detect start time / version info from previous result metrics.json
    const snap_id = snap_dir.split('/archive/').at(-1)
    const existing_metrics = path.join(snap_dir, 'metrics.json')
    let {start_time, VERSION} = {start_time: '1970-01-01T00:00:00.000Z', VERSION: '19700101000000'}
    try {
        ;({start_time, VERSION} = JSON.parse(await fs.promises.readFile(existing_metrics, 'utf-8')));
    } catch(err) {
        // continue normally, overwriting existing files is fine if they're broken to begin with
    }
 
    // create new version folder based on metrics.json start_time (or epoch time as fallback for legacy output)
    const version_dir_name = VERSION || versionStrFromDate(start_time)
    const version_dir = path.join(snap_dir, 'versions', version_dir_name)
    await fs.promises.mkdir(version_dir, {recursive: true})

    // move all result files from snapshot_dir root into version folder
    const existing_snapshot_files =
        (await fs.promises.readdir(snap_dir, {withFileTypes: true}))
            .filter(dirent => {
                if (dirent.name.startsWith('.')) return false    // ignore hidden files, dont version them
                if (dirent.name == 'versions') return false      // dont try to move versions folder into itself
                if (dirent.isSymbolicLink()) return false        // skip existing symbolic links
                return (dirent.isFile() || dirent.isDirectory()) // dont try to version sockets/FIFOs/devs etc.
            })

    if (existing_snapshot_files.length) {
        console.log(`[📅] Moving snapshot results into version dir: ./data/archive/${snap_id}/* ->`.padEnd(82), `./data/archive/${snap_id}/versions/${VERSION}/`)
    }
    
    const snapshot_files = await getDirInfo(snap_dir, {withRoot: false, filter: ({relpath}) => !relpath.startsWith('versions')})
    const version_files = await getDirInfo(version_dir, {withRoot: false})

    for (const {name} of existing_snapshot_files) {
        const snapdir_entry_abspath = path.join(snap_dir, name)
        const versioned_entry_abspath = path.join(version_dir, name)

        const snapshot_entry = snapshot_files[name]
        const version_entry = version_files[name]

        if (snapshot_entry && version_entry) {
            // a conflicting file/dir already exists in the destination path
            // we have a few options here, we can try to merge them, or we can create a new version

            if (snapshot_entry.sha256 == version_entry.sha256) {
                // both are the same already, delete the duplicate (leaving the copy inside the version dir)
                // if (snapshot_entry.is_dir) {
                //     await fs.promises.rmdir(snapshot_entry.abspath, {recursive: true})
                // } else {
                //     await fs.promises.unlink(snapshot_entry.abspath)
                // }
                // console.warn(`[!] Found harmless exact duplicate files, leaving as is: ${snapshot_entry.summary} and ${version_entry.summary}`)
            } else {
                // both are different,
                if (snapshot_entry.num_bytes > version_entry.num_bytes) {
                    // snapshot entry is bigger, keep it and delete version entry?
                } else {
                    // version entry is bigger, keep it and delete snapshot entry
                }
                console.warn('    ', snapshot_entry.summary)
                console.warn('    ', version_entry.summary)
                // throw `Found conflicting duplicate files with different contents: ${name}`
            }
        } else {
            // mv ./data/archive/<snap_id>/example.txt -> ./data/archive/<snap_id>/versions/<version_id>/example.txt
            await fs.promises.rename(snapdir_entry_abspath, versioned_entry_abspath)
            console.log(`  ↣ ${prettyPath(snapdir_entry_abspath)} ->`.padEnd(82), prettyPath(versioned_entry_abspath))
        }
    }
}

// Extractor definition
// {
//  phase: setup | load | sync1 | async1 | sync2 | close
//  name: 'media' | 'photos', 'wget', 'singlefile'
//  
//  shouldRun(page, page_state)
    
    // pageSetup
    // pageLoad
    // pageInteraction         clicking around/scrolling
    // archivePhase1           sync
    // archivePhase2           async
    // archivePhase3           async
    // pageClose

//  execute(page, page_state)
//  validateResult(page, page_state)
// }

async function clearSnapshotDirSymlinks(snap_dir) {
    // delete all archive/<id>/* symlinks in preparation for new snapshot output to be placed there

    const existing_symlinks =
        (await fs.promises.readdir(snap_dir, {withFileTypes: true}))
            .filter(dirent => {
                if (dirent.name.startsWith('.')) return false    // ignore hidden files, dont version them
                if (dirent.name == 'versions') return false      // dont try to move versions folder into itself
                return dirent.isSymbolicLink()
            })

    for (const {name: existing_symlink} of existing_symlinks) {
        await fs.promises.unlink(path.join(snap_dir, existing_symlink))
        // if symlinks are not cleared before starting, it can cause issues with outputs writing into previous versions folders
        // e.g. screerecording saves to ./media which could be pointing to previous version's ./versions/<olddate>/media
    }
}

async function symlinkBestSnapshotResults(snap_dir) {
    // move any existing files into versions/<date> folder (clear out main folder)
    // symlink latest files from versions/<date>/* into main folder
    
    await fs.promises.mkdir(path.join(snap_dir, 'versions'), {recursive: true})
    process.chdir(snap_dir)

    const metrics_file = path.join(snap_dir, 'metrics.json')
    // if (!fs.existsSync(metrics_file) || (await fs.promises.lstat(metrics_file)).isSymbolicLink()) {
    //     console.warn('[⚠️] Warning, found partial dirty snapshot state (did the snapshot get interrupted?)', snap_dir)
    // }

    // move output files into versioned folder
    await collectSnapshotDirVersionFiles(snap_dir)    

    // clear any existing symlinks
    await clearSnapshotDirSymlinks(snap_dir)

    // assert task dir is empty and contains no bare files that might get overwritten, also asserts version dirs are valid
    await assertSnapshotDirIsValid(snap_dir, {is_empty: true})


    const version_dirs = (await fs.promises.readdir(path.join(snap_dir, 'versions'))).sort()   // earliest to latest
    const most_recent = version_dirs.at(-1)

    // for each version dir in versions/ (oldest -> newest)
    for (const version_dir of version_dirs) {
        if (version_dir.startsWith('.')) continue

        const version_dir_abspath = path.join(snap_dir, 'versions', version_dir)
        const version_dir_files = (
            (await fs.promises.readdir(version_dir_abspath))
                .filter(filename => !filename.startsWith('.')))

        // iterate through all the files/folders in the version dir
        for (const filename of version_dir_files) {
            const snapdir_entry = path.join(snap_dir, filename)                                // ./data/archive/<snapid>/filename
            const versiondir_entry = path.join(snap_dir, 'versions', version_dir, filename)    // ./data/archive/<snapid>/versions/<versionid>/filename
            
            if (fs.existsSync(snapdir_entry)) {
                // if an entry already exists in the snapshot root for this filename
                if ((await fs.promises.lstat(snapdir_entry)).isSymbolicLink()) {
                    // if a symlink already exists in the root with the same name,
                    // check if the version file we're looking at is a better candidate to replace it

                    const existing_abspath = await fs.promises.realpath(snapdir_entry)
                    const desired_abspath = path.join(version_dir_abspath, filename)
                    if (existing_abspath != desired_abspath) {
                        // check if the new candidate is larger or if the existing symlink is larger   (largest file = most likely to be highest quality capture data)
                        const largest_path = await getLargestPath(existing_abspath, desired_abspath)
                        if (largest_path != (await fs.promises.realpath(existing_abspath))) {
                            const larger_version = path.basename(path.dirname(largest_path))
                            const larger_abspath = path.join(snap_dir, 'versions', larger_version, filename)
                            
                            // console.log('    - swapping for larger file:', filename, '->', larger_abspath.split('/archive/').at(-1))
                            await overwriteSymlink(larger_abspath, snapdir_entry, {search_limit: snap_dir})
                        } else {
                            // console.log('    - leaving larger file:', largest_path.split('/archive/').at(-1))
                        }
                    } else {
                        // leave existing symlink pointing to current version file, nothing to change
                        // console.log('    - leaving current file:', existing_abspath.split('/archive/').at(-1))
                    }
                } else {
                    // clearSnapshotDirSymlinks() should have already cleared these files out!
                    throw `Non-symlink file found in root of snapshot dir! Refusing to overwrite: ${prettyPath(snapdir_entry)}`
                }
            } else {
                // no entry exists in the snapshot root for this filename, create one by linking to the version file
                await overwriteSymlink(versiondir_entry, snapdir_entry, {search_limit: snap_dir})
            }
            // if (version_dir == most_recent) {
            //     // only log most recent links even though we link older ones too (otherwise its too noisy)
            //     console.log(`  🔗 ./${filename} -> ./${versiondir_entry} linking...`)
            // }
        }
    }

    return snap_dir
}

async function assertSnapshotDirIsValid(snap_dir, {is_empty=false}={}) {
    process.chdir(snap_dir)
    console.log()
    console.log(`[☑️] Checking that snapshot records are valid...`)

    // get all directory entries in archive/<snapshot_id>/*
    const snapshot_dir_entries =
        (await fs.promises.readdir(snap_dir, {withFileTypes: true}))
            .filter(dirent => {
                if (dirent.name.startsWith('.')) return false
                if (dirent.name == 'versions') return false
            })

    // assert versions folder exists and is not a symbolic link
    const versions_dir = path.join(snap_dir, 'versions')
    assert(fs.existsSync(versions_dir))
    assert(!(await fs.promises.lstat(versions_dir)).isSymbolicLink())

    // if it should be empty, check that no loose files exist
    if (is_empty) {
        assert(!snapshot_dir_entries.length, `Found loose files in snapshot-dir that shouldn't be there! ${snap_dir}`)
    }

    // assert all non-hidden files in snapshot dir are symbolic links to actual data in versions/<date>/*
    for (const snapshot_dir_entry of snapshot_dir_entries) {
        if (snapshot_dir_entry.name.startsWith('.')) continue
        if (snapshot_dir_entry.name == 'versions') continue
        assert(snapshot_dir_entry.isSymbolicLink(), `Found non-symbolic link in root of snapshot dir! ${snap_dir}/${snapshot_dir_entry.name}`)
        assert(fs.existsSync(snapshot_dir_entry.name), `Found broken symbolic link in root of snapshot dir! ${snap_dir}/${snapshot_dir_entry.name}`)
    }

    const version_entries = (
        (await fs.promises.readdir(versions_dir))
            .filter(foldername => !foldername.startsWith('.'))
            .sort())

    console.log(`  √ ${prettyPath(versions_dir)}`, version_entries.length)

    for (const version_dir of version_entries) {
        await assertVersionDirIsValid(path.join(versions_dir, version_dir))
    }

    // write snapshot dir file listing w/ sizes & hashes to .files.json
    const directory_info = await getDirInfo(snap_dir, {withRoot: true, withHelpers: false, maxdepth: 3})
    await overwriteFile(path.join(snap_dir, '.files.json'), directory_info)
}

async function assertVersionDirIsValid(version_dir) {
    const dirname = path.parse(version_dir).name
    assert(fs.existsSync(version_dir), `Version dir does not exist: ${prettyPath(version_dir)}`)

    const dirent = await fs.promises.lstat(version_dir)
    assert(dirent.isDirectory() && !dirent.isSymbolicLink(), `Found non-directory in versions dir! ${prettyPath(version_dir)}`)
    
    const unix_epoch = '19700101000000'
    const is_name_valid_datestr = /^\d+$/.test(dirname) && (dirname.length == 14) && (dirname.startsWith('2') || dirname == unix_epoch) && parseVersionDateStr(dirname)
    assert(is_name_valid_datestr, `Version directories must be a 14-character long date string like 20251231235959! ${dirname}`)

    // get all directory entries in archive/<snapshot_id>/versions/<version_id>/*
    const version_dir_entries = (
        (await fs.promises.readdir(version_dir, {withFileTypes: true}))
            .filter((dirent) => !dirent.name.startsWith('.')))

    // assert version dir contains only actual snapshot output files (not-symbolic links or other version dirs)
    for (const version_dir_entry of version_dir_entries) {
        assert(version_dir_entry.name != 'versions', `Version dir cannot contain another versions folder! ${prettyPath(version_dir)}/versions`)
        assert(!version_dir_entry.isSymbolicLink(), `Version dir cannot contain symbolic link! ${prettyPath(version_dir)}/${version_dir_entry.name}`)
    }

    // color highlight the unix epoch version in black, and any version created today in blue
    let pretty_dirname = dirname
    if (dirname == unix_epoch) {
        pretty_dirname = ANSI.black + unix_epoch + ANSI.reset
    }
    const today = versionStrFromDate(new Date(), {withDate: true, withTime: false})
    if (dirname.startsWith(today)) {
        pretty_dirname = ANSI.blue + dirname + ANSI.reset
    }

    // write version dir file listing w/ sizes & hashes to .files.json
    const directory_info = await getDirInfo(version_dir, { withRoot: true, withHelpers: false, maxdepth: 3 })
    await overwriteFile(path.join(version_dir, '.files.json'), directory_info)

    console.log(`    √ ./versions/${pretty_dirname} contains`, version_dir_entries.length, 'results')
}

async function setupSnapshotDB({ original_url, start_time, snapshot_dir }) {
    // setup Snapshot database row, finding it if it already exists or creating a new one

    const timestamp = snapshot_dir.split('/').at(-1)
    const search_attrs = { url: original_url, timestamp }
    const update_attrs = { url: original_url, timestamp, added: start_time, title: null }

    let snapshot = await Snapshot.findOne({ where: search_attrs });
    let created = false
    if (!snapshot) {
        snapshot = await Snapshot.findOne({ where: {url: original_url} });
        if (snapshot) {
            // console.warn(`[X] Found DB Snapshot [${timestamp}](${original_url.substring(0, 30)}...) that has different timestamp from existing dir ${prettyPath(snapshot_dir)}!`)
            // throw 'Snapshot DB record does not match filesystem path!'
        } else {
            console.log(`[+] Creating new DB Snapshot [${timestamp}](${original_url.substring(0, 30)}...) for ${prettyPath(snapshot_dir)}...`)
            // ;([snapshot, created] = await Snapshot.findOrCreate({where: search_attrs, defaults: update_attrs }));
            // throw 'Wanted to create new Snapshot but refusing to modify DB during testing!'
        }
    }

    // assert(snapshot && (snapshot instanceof Snapshot))
    return snapshot
}

async function setupViewport(page, _page_state) {
    // setup viewport
    await page.setViewport(DEFAULT_VIEWPORT);
    await page.setGeolocation(DEFAULT_GEOLOCATION);
    // await page.setBypassCSP(true);             // bypass CSP restrictions (requires --disable-web-security)
    page.setDefaultTimeout(DEFAULT_TIMEOUT);

    // Optional: emulate a mobile device
    //  await page.emulate(puppeteer.devices['iPhone 6']);

    // Configure light mode/dark mode & accessibility reduced motion preferences
    await page.emulateMediaFeatures([
        {name: 'prefers-color-scheme', value: DEFAULT_COLOR_SCHEME},
        {name: 'prefers-reduced-motion', value: 'reduce'},
    ]);

    // Setup headers & deterministically chose a random referrer based on URL
    const rand_idx = hashCode(await page.url()) % DEFAULT_REFERRERS.length
    await page.setExtraHTTPHeaders({
        ...DEFAULT_HEADERS,
        referrer: DEFAULT_REFERRERS[rand_idx],
    })

    // Setup alert to trigger if site tries to sniff whether we are a bot
    function sniffDetector() {
        const userAgent = window.navigator.userAgent;
        const platform = window.navigator.platform;
        // @ts-ignore
        window.navigator.__defineGetter__('userAgent', function () {
            // @ts-ignore
            window.navigator.sniffed = true;
            return userAgent;
        });
        // @ts-ignore
        window.navigator.__defineGetter__('platform', function () {
            // @ts-ignore
            window.navigator.sniffed = true;
            return platform;
        });
    }
    await page.evaluateOnNewDocument(sniffDetector);
    // @ts-ignore
    const was_sniffed = await page.evaluate(() => (!!window.navigator.sniffed))
    if (was_sniffed) {
        console.warn('[⚠️] Site tried to sniff if we are a bot! Site may be difficult to archive.')
    }
    
    return page
}

async function setupModalAutoClosing(page, page_state, {timeout=1_250}={}) {
    page.on('dialog', (dialog) => { 
        console.log(`[👆] Auto-closing modal that popped up: ${dialog.message()}...`)
        setTimeout(() => {try { dialog.accept() } catch(err) {}}, timeout);
    })

    // if you expect a file-upload dialog, use this to catch it instead:
    // const [fileChooser] = await Promise.all([
    //   page.waitForFileChooser(),
    // ]);
    // await fileChooser.accept(['/tmp/myfile.pdf']);
    page.on('close', () => {
        try {
            page.off('dialog')
        } catch(err) {}
    })
}

async function startScreenrecording(page, page_state, {duration_limit=60, codec='libx264'}={}) {
    await fs.promises.mkdir(path.dirname(SCREENRECORDING_PATH(page)), {recursive: true})
    // console.log(`[🎬] Starting screen-recording stream...`.padEnd(82), prettyPath(SCREENRECORDING_PATH(page)))
    
    // alternative: interact with low-level puppeteer screencast API directly
    // using puppeteer.page.screencast: https://pptr.dev/api/puppeteer.page.screencast
    // const recorder = await page.screencast({path: SCREENRECORDING_PATH(page)});

    // alternative: use puppeteer-stream for .webm/.mp4 screen recordings with tab audio included
    // works sometimes but has a few issues, e.g.: https://github.com/SamuelScheit/puppeteer-stream/issues/8

    // alternative: puppeteer-screen-recorder (most compatible/stable but doesn't include tab audio output)
    const recorder = new PuppeteerScreenRecorder(page, {
        followNewTab: false,
        recordDurationLimit: duration_limit,
        // fps: 25,
        // ffmpeg_Path: '<path of ffmpeg_path>' || null,
        // videoFrame: {
        //   width: 1024,
        //   height: 768,
        // },
        // videoCrf: 18,
        videoCodec: codec,
        // videoPreset: 'ultrafast',
        // videoBitrate: 1000,
        // autopad: {
        //   color: 'black' | '#35A5FF',
        // },
        // aspectRatio: '4:3',
    });
    page_state.recorder = recorder
    await recorder.start(SCREENRECORDING_PATH(page))

    page.on('close', async () => {await saveScreenrecording(page, page_state)});
    return page_state
}

async function startResponseSaving(page, page_state) {
    const dir = RESPONSES_PATH(page)
    await fs.promises.mkdir(dir, {recursive: true})

    console.log(`[🌄] Starting raw response bytes recording...`.padEnd(82), prettyPath(dir) + '/')

    // Document, Stylesheet, Image, Media, Font, Script, TextTrack, XHR, Fetch, Prefetch, EventSource, WebSocket, Manifest, SignedExchange, Ping, CSPViolationReport, Preflight, Other
    const types_to_save = [
        // 'document',
        'script',
        'stylesheet',
        'font',
        'image',
        'media',
        'xhr',
        'websocket',
    ]

    // reset responses index file to empty
    const responses_log_path = path.join(dir, 'index.jsonl')
    await overwriteFile(responses_log_path, '')

    // add handler to save all image repsonses into output directory
    page.on('response', async (response) => {
        try {

            const timestamp = versionStrFromDate(new Date(), {withDate: true, withTime: true, withSeconds: true, withMilliseconds: true})

            if (!page_state.main_response && (response.request().url() == page_state.original_url)) {
                // save first response as main page response (if we havent already caught it earlier)
                page_state.main_response = response
            }

            const status = response.status()
            if ((status >= 300) && (status < 500)) {
                // console.log('Got bad response from', response.url(), 'to', response.headers()['location'])
                return
            }
            const request = response.request()
            const resourceType = request.resourceType()
            const url_scheme = (response.url() || request.url()).split(':')[0].toLowerCase()
            const method = (url_scheme === 'data') ? 'DATA' : request.method()

            // console.log('    ', resourceType, response.url())
            if (types_to_save.includes(resourceType)) {
                // create ./responses/xhr/www.facebook.com/static/images/icons/ subdir based on hostname + path
                const resource_type_dir = path.join(dir, resourceType)
                const url = new URL(response.url())
                let subdir = resource_type_dir
                const url_path = (url.pathname || '').slice(0, 250).endsWith('/')
                    ? (url.pathname || '').slice(0, 250)
                    : path.dirname((url.pathname || '').slice(0, 250))

                // determine subdirectory based on url type (handles http:,https:,file:,data:,chrome-extension:,about:,etc.)
                if (!URL_SCHEMES_IGNORED.includes(url_scheme)) {
                    // is a normal http:// or https:// url, use the domain + path to construct subdirectory
                    subdir = path.join(resource_type_dir, (url.hostname || 'data').slice(0, 250), url_path)
                } else if (url_scheme == 'data') {
                    // is a data:... url, store in ./data subdirectory
                    subdir = path.join(resource_type_dir, 'data')
                } else {
                    // is a chrome-extension:// or other special url, use the extension id + path to construct subdirectory
                    const url_path = path.dirname((url.pathname || '').slice(0, 999))
                    subdir = path.join(resource_type_dir, url_scheme, (url.hostname || 'data').slice(0, 250), url_path)
                }

                // write response to responses/all/1716861056899__https%3A%2F%2Fwww.instagram.com%2Fgraphql%2Fquery.json
                let abspath = null
                let resp_mimetype = null
                let extension = ''
                let uniq_filename = null
                let uniq_abspath = null
                let symlink_abspath = null
                let responseSha256 = null
                try {
                    await fs.promises.mkdir(path.join(dir, 'all'), {recursive: true})
                    try {
                        await fs.promises.mkdir(subdir, {recursive: true})
                    } catch(err) {
                        subdir = subdir + '.dir' // TODO: apply this workaround to parent path entries too
                        try {
                            await fs.promises.mkdir(subdir, {recursive: true})
                        } catch(err) {
                            subdir = path.join(resource_type_dir, 'data')
                            await fs.promises.mkdir(subdir, {recursive: true})
                        }
                    }
                    ;({abspath: symlink_abspath, resp_mimetype, extension} = await detectFilename({page, response, dir: subdir, resourceType}))
                    
                    // responses/all/1716861056899__https%3A%2F%2Fwww.instagram.com%2Fgraphql%2Fquery.json
                    uniq_filename = `${timestamp}__${method}__` + [encodeURIComponent(url.href).slice(0, 64).replaceAll('/', '_').replace(new RegExp(`.${extension}$`), ''), extension].filter(s => s.length).join('.')
                    uniq_abspath = path.join(dir, 'all', uniq_filename)


                    let bytesBuffer = null
                    try {
                        bytesBuffer = await response.buffer()
                    } catch(err) {
                        if (String(err).includes("Cannot read properties of undefined (reading 'body')")) {
                            // not sure why it's happening but seems to be too late to caputre body sometimes? possible race condition
                        } else {
                            console.warn('[⚠️] Failed to save response bytes for:', response.request().url(), err)
                        }
                    }
                    if (bytesBuffer) {
                        // write response data into ./all/<TS>__<METHOD>__<URL>.<EXT>
                        await overwriteFile(uniq_abspath, bytesBuffer)
                        
                        responseSha256 = crypto.createHash('sha256').update(bytesBuffer).digest('hex')

                        // write symlink file to ./<TYPE>/<DOMAIN>/...<PATH>/<FILENAME>.<EXT>   ->  ./all/<TS>__<METHOD>__<URL>.<EXT>
                        await overwriteSymlink(uniq_abspath, symlink_abspath, {relative: dir, mkdirs: true, search_limit: dir})
                    }
                    // console.log('    ->', symlink_abspath)
                } catch(err) {
                    // dont do anything for redirectresponses, error responses, etc.
                    console.warn(err)
                }

                const urlSha256 = crypto.createHash('sha256').update(String(request.url())).digest('hex')
                // const headersSha256 = crypto.createHash('sha256').update(String(request.headers()))   // someday we may want to save headers hashes too

                const truncated_url = (method == 'DATA') ? request.url().slice(0, 128) : request.url()   // don't duplicate bytes in data: urls (we already saved them in the file)

                // this is essentially replicating the functionality of a WARC file, but in directory + index.jsonl form
                await fs.promises.appendFile(
                    responses_log_path,
                    JSON.stringify({
                        ts: timestamp,
                        method,
                        url: truncated_url,
                        urlSha256,
                        postData: request.postData(),
                        response_url: ((method != 'DATA') && (url.href != request.url())) ? url.href : undefined,
                        status,
                        resourceType,
                        mimeType: resp_mimetype,
                        responseSha256,
                        path: uniq_abspath?.replace(dir, '.'),
                        symlink_path: symlink_abspath?.replace(dir, '.'),
                        extension,
                    }) + '\n',
                    'utf-8',
                )
            }
        } catch(err) {
            // we should never throw hard errors here because there's nothing above us to catch it
            // and we dont want to crash the entire CDP session / browser / main node process
            console.warn('[❌] Error in response handler (set in startResponseSaving):', err)
        }
    });
    // handled by stopMetadataRecording():
    // page.on('close', () => {
    //     page.off('response')
    // })
}

function dedupeCookies(cookies) {
    const len_before = cookies.length

    const allowed_cookie_attrs = ['domain', 'path', 'name', 'value', 'expires', 'sameSite', 'sourceScheme', 'url', 'priority', 'secure', 'httpOnly']

    const deduped_cookies = {}
    for (const cookie of cookies) {
        try {
            const unique_id = `${cookie.domain}${cookie.path}${cookie.name}`
            deduped_cookies[unique_id] = {
                ...(deduped_cookies[unique_id] || {}),
                ...cookie,
                expires: 2147483640,    // max allowed expiry time (2038-01-18)
                session: false,         // make sure cookies dont expire at browser close time
                secure: false,          // make cookie restrictions more lax (for archiving scripts)
                httpOnly: false,        // make it easier to tamper with cookies from JS (for archiving scripts)
                
                // "path": "/",
                // "expires": 2147483641,
                // "size": 194,
                // "httpOnly": false,
                // "secure": false,
                // "session": false,
                // "priority": "High",
                // "sameParty": false,
                // "sourceScheme": "Secure",
                // "sourcePort": 443
                
                // and more...                  https://pptr.dev/api/puppeteer.cookieparam
            } as Cookie

            if (!deduped_cookies[unique_id].value) {
                delete deduped_cookies[unique_id]
                continue
            }
            if (deduped_cookies[unique_id].name.startsWith('__')) {
                // cookies that start with __ must be secure, see https://github.com/puppeteer/puppeteer/issues/6806
                deduped_cookies[unique_id].secure = true
                deduped_cookies[unique_id].sourceScheme = 'Secure'
            }
            if (deduped_cookies[unique_id].domain.startsWith('.')) {
                deduped_cookies[unique_id].sameParty = false
                deduped_cookies[unique_id].domain = deduped_cookies[unique_id].domain.slice(1)
            }
            
            for (const key of Object.keys(deduped_cookies[unique_id])) {
                if (!allowed_cookie_attrs.includes(key)) {
                    delete deduped_cookies[unique_id][key]
                }
            }
        } catch(err) {
            console.error('[❌] Failed to parse cookie during deduping', cookie)
            throw err
        }
    }
    // console.log(`[🍪] Deduped ${len_before} cookies to ${Object.keys(deduped_cookies).length}...`)

    return Object.values(deduped_cookies) as Cookie[]
}

async function loadCookiesTxt() {
    const cookies = [] as Cookie[]
    return cookies  // write-only from chrome -> files for now

    if (fs.existsSync(COOKIES_TXT_PATH)) {
        // console.log(`[🍪] Loading cookies/localStorage/sessionStorage from ${COOKIES_TXT_PATH}...`)

        // Read from to cookies.txt file using tough-cookie + @root/file-cookie-store
        const cookies_store = new FileCookieStore(COOKIES_TXT_PATH, {auto_sync: false, lockfile: false});
        cookies_store.getAllCookiesAsync = util.promisify(cookies_store.getAllCookies);
        const exported_cookies = await cookies_store.getAllCookiesAsync()
        for (const cookie of exported_cookies) {
            const cookie_from_tough = cookie.toJSON()
            const domain = cookie_from_tough.hostOnly ? `.${cookie_from_tough.domain}` : cookie_from_tough.domain
            const cookie_for_puppeteer: Cookie = {
                domain,
                name: cookie_from_tough.key,
                path: cookie_from_tough.path,
                value: cookie_from_tough.value,
                secure: cookie_from_tough.secure || false,
                httpOnly: cookie_from_tough.httpOnly || false,
                session: false,
                expires: (new Date(cookie_from_tough.expires)).valueOf()/1000,
                size: undefined,
            }
            // console.log('COOKIE_FROM_TOUGH_TXT', cookie_from_tough, cookie_for_puppeteer)
            cookies.push(cookie_for_puppeteer)
        }
    }
}

type AuthJSON = {
    cookies: Cookie[],
    sessionStorage: any,
    localStorage: any,
}

async function loadAuthStorage(page, {client}, {apply=true}={}) {
    var {
        cookies,
        sessionStorage,
        localStorage,
    }: AuthJSON = {cookies: [], sessionStorage: {}, localStorage: {}}
    
    if (!LOAD_AUTH_STORAGE) {
        // dont read auth from filesystem auth.json/cookies.txt, just rely on existing cookies in chrome profile
        return {cookies, sessionStorage, localStorage}
    }

    if (fs.existsSync(COOKIES_TXT_PATH)) {
        try {
            cookies = await loadCookiesTxt()
        } catch(err) {
            console.warn('[⚠️] Loaded invalid cookies.txt, moved it to cookies.txt.corrupted (did two processes try to change it at the same time?)')
            await fs.promises.rename(COOKIES_TXT_PATH, COOKIES_TXT_PATH + '.corrupted')
        }
        // console.log(`[🍪] Loading cookies from cookies.txt...`, cookies.length)
    }

    if (fs.existsSync(AUTH_JSON_PATH)) {
        try {
            var {
                cookies: auth_json_cookies,
                sessionStorage,
                localStorage,
            } = JSON.parse(await fs.promises.readFile(AUTH_JSON_PATH, 'utf-8'));
            cookies = [...cookies, ...auth_json_cookies]
            // console.log(`[🍪] Loading cookies from auth.json...`, auth_json_cookies.length)
        } catch(err) {
            console.warn('[⚠️] Loaded invalid auth.json, moved it to auth.json.corrupted (did two processes try to change it at the same time?)')
            await fs.promises.rename(AUTH_JSON_PATH, AUTH_JSON_PATH + '.corrupted')
        }
    }

    cookies = dedupeCookies(cookies)

    if (apply) {
        console.log(`[🍪] Loading stored cookies/localStorage/sessionStorage into session...`, cookies.length)

        // if (cookies?.length) {
        //     try {
        //         // try setting all at once first (much faster)
        //         await page.setCookie(...cookies)
        //     } catch(err) {
        //         // if any errors, fall back to setting one-by-one so that individual error can be caught
        //         for (const cookie of cookies) {
        //             try {
        //                 await page.setCookie(cookie);
        //             } catch(err) {
        //                 console.error('[❌] Failed to set cookie', cookie)
        //                 throw err
        //             }
        //         }
        //     }
        // }
        const origin = await page.evaluate(() => window.location.origin)

        await page.evaluate((savedSessionStorage) => {
            for (const [key, value] of Object.entries(savedSessionStorage)) {
                sessionStorage[key] = value;
            }
        }, sessionStorage[origin] || {});
      
        await page.evaluate((savedLocalStorage) => {
            for (const [key, value] of Object.entries(savedLocalStorage)) {
                localStorage[key] = value;
            }
        }, localStorage[origin] || {});

        // origin/auth context changes when we do page.goto so we have to hook pageload and apply it then as well
        // https://stackoverflow.com/questions/51789038/set-localstorage-items-before-page-loads-in-puppeteer
        await page.evaluateOnNewDocument(({sessionStorage, localStorage}) => {
            const origin = window.location.origin;

            for (const [key, value] of Object.entries(sessionStorage[origin] || {})) {
                window.sessionStorage.setItem(key, value as string)
            }
            for (const [key, value] of Object.entries(localStorage[origin] || {})) {
                window.localStorage.setItem(key, value as string)
            }
            
        }, {sessionStorage, localStorage});
    }

    return {cookies, sessionStorage, localStorage}
}

async function loadCloudflareCookie(page, {original_url}, {timeout=20_000}={}) {
    // make request to FlareSolverr server to get magic cookies that let us bypass cloudflare bot detection
    // docker run -p 8191:8191 -e LOG_LEVEL=info ghcr.io/flaresolverr/flaresolverr


    // alternatives if this stops working:
    // - https://github.com/omkarcloud/botasaurus
    // - https://github.com/ultrafunkamsterdam/nodriver
    // - https://github.com/Akmal-CloudFreed/CloudFreed-CloudFlare-bypass
    // - https://github.com/VeNoMouS/cloudscraper

    const query = { url: original_url, cmd: "request.get", maxTimeout: timeout }
    try {
        const response = await fetch(FLARESOLVERR_API_ENDPOINT, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(query),
        });
        const data = await response.json();

        const new_cookies = (data?.solution?.cookies || []).map(cookie => ({
            ...cookie,
            'expires': 2147483640,       // overwrite expiration to 32bit maximum timestamp (2038-01-18)
            'secure': false,             // cookie value is plain text (not encrypted/encoded)
        }))

        if (new_cookies.length) {
            console.log(`[☑️] Got Cloudflare bypass cookies (${new_cookies.length}) from FlareSolverr API...`)
            await page.setCookie(...new_cookies);
            return new_cookies
        } else {
            const error_str = JSON.stringify(data?.message || data, null, 4)
            throw `Bad FlareSolverr Response: ${error_str}`
        }

    } catch (error) {
        if (JSON.stringify(error).includes('Challenge not detected')) {
            console.log('[☑️] Page is accessible without FlareSolverr Cloudflare bypass.')
        } else {
            console.warn('[❌] Failed to get Cloudflare bypass cookies from FlareSolverr API.', error)
        }
    }
    return []
}

async function setupURLRewriting(page, page_state) {
    await page.setRequestInterception(true);

    const rewrites = URL_REWRITES.sort((a, b) => (a.idx || 0) - (b.idx || 0))

    page.on('request', interceptedRequest => {
        if (interceptedRequest.isInterceptResolutionHandled()) return;

        const original_url = interceptedRequest.url()

        // apply all the rewrites in order to the request URL
        let url = original_url
        for (const rewrite of rewrites) {
            const new_url = url.replace(rewrite.pattern, rewrite.replacement)
            // console.log(rewrite, url, new_url)
        
            // if url is rewritten to an emptystring, abort the request
            if (!new_url) {
                console.warn('[🟥] Request blocked', rewrite.pattern, ':', url)
                interceptedRequest.abort()
                return
            }
            else if (new_url && new_url != url) {
                // console.warn('[📳] Request rewritten', rewrite.pattern, rewrite.replacement, ':', url, '->', new_url)
                console.warn('[📳] Request rewritten', rewrite.pattern, ':', new_url)
                url = new_url
            }
        }

        if (url == original_url) {
            // if url is unchanged, continue request flow as-is
            interceptedRequest.continue()
        } else {
            // otherwise redirect the browser to our rewritten version
            interceptedRequest.respond({
                status: 302,
                headers: {
                    location: url,
                    'x-redirect-by': 'ArchiveBox.setupURLRewriting',
                },
            })
        }
    });
    // handled by stopMetadataRecording():
    // page.on('close', () => {
    //     page.off('request')
    //     page.setRequestInterception(false)
    // })
}

async function startMetadataRecording(page, {original_url, version, client, traffic_log, console_log, redirects}) {
    // update helper state on page
    page._original_url = (original_url || (await page.url())).toString()

    // DEBUGGING: helpers for repl() debugging, dont rely on these (global state is badd mmkay)
    // page._client = client || page._client || await page.target().createCDPSession()
    // page._redirects = redirects
    // page._traffic_log = traffic_log

    // add initial entry to page redirect log
    redirects[original_url] = {
        idx: 0,
        url: original_url,
        src: null,
        type: 'Initial',
        wallTime: Date.now()/1000,
        frameId: page.mainFrame()._id,
        requestId: null,
        initiator: {type: "user"},
        isMainFrame: true,
    }
    
    // DEBUGGING: record optional chrome debug trace with screenshots (heavy)
    // try {
    //     await page.tracing.stop()
    //     await wait(200)
    // } catch(err) {}
    // try {
    //     await page.tracing.start({path: TRACE_PATH(page), screenshots: true});
    // } catch(err) {}

    let last_main_frame_url = original_url

    // setup network request intercepts handler
    const addCDPRequestDataListener = (eventName) => {
        client.on(eventName, event => {
            try {
                // save any HTTP/JS redirects to redirects for saveRedirects(page) to use later on
                const new_url = event.documentURL
                const http_status = event.redirectResponse?.status || 0
                const is_new_url = (new_url !== original_url) && !redirects[new_url]
                const is_main_frame_navigation = (event.frameId == page.mainFrame()._id)
                const is_http_redirect = (300 < http_status) && (http_status < 400)

                if (new_url && is_new_url && (is_main_frame_navigation || is_http_redirect) && event.type == 'Document') {
                    const new_redirect_entry = {
                        url: new_url,
                        src: event.redirectResponse?.url || last_main_frame_url,
                        type: http_status || 'JS',
                        wallTime: Date.now()/1000,
                        frameId: event.frameId,
                        requestId: event.requestId,
                        initiator: event.initiator,
                        idx: Object.keys(redirects).length,
                        isMainFrame: is_main_frame_navigation,
                    }
                    redirects[new_url] = new_redirect_entry
                    if (is_main_frame_navigation) {
                        ALREADY_ARCHIVED.add(new_redirect_entry.url.slice(0, 4096))  // we're already archiving this tab as it redirects, dont create a duplicate archive for the destination
                        console.warn(`[➡️] NAVIGATION[${new_redirect_entry.type}]${ANSI.blue} ${last_main_frame_url} ${ANSI.reset}\n                  ->${ANSI.blue} ${new_redirect_entry.url} ${ANSI.reset}`)
                        last_main_frame_url = new_url
                    }
                }

                if (event.loaderId) {
                    traffic_log[event.loaderId] = traffic_log[event.loaderId] || {}       // make sure loader is also in requests list first
                    // sometimes it's not in the list if we start archiving too late / after a page's initial request was already made
                }

                // save to traffic_log as {8BC2087A2CCEF28017099C0E10E87440: {Network.eventWillBeSent: {eventId,loaderId, request|response, ...}}
                // https://stackoverflow.com/questions/47078655/missing-request-headers-in-puppeteer?noredirect=1&lq=1
                traffic_log[event.requestId] = traffic_log[event.requestId] || {}
                Object.assign(traffic_log[event.requestId], { [eventName]: event })
                
                // DEBUGGING: log page visits and navigation events to console
                // if (event?.response?.status) {
                //     // if we're expecting an HTML response, then we assume it's a page visit & log it to console
                //     const acceptMimeType = traffic_log[event.requestId]['Network.requestWillBeSentExtraInfo']?.headers?.accept
                //     if (acceptMimeType && acceptMimeType.includes('text/html')) {
                //         // log any HTML page responses (less noisy)
                //         console.log(`[>] GOT ${event.documentURL}: ${event.response.status} ${event.response.url} (${event.response.mimeType})`)
                //     } else {
                //         // log ALL responses, inclusing JS,CSS,Images,etc. (very noisy)
                //         // console.log(`      > ${event.response.status} ${event.response.url} (${event.response.mimeType})`)
                //     }
                // }
            } catch(err) {
                console.warn('[X] Error during request/response handler (startMetadataRecording.addCDPRequestDataListener)')
                console.warn(err)
            }
        })
    }
    addCDPRequestDataListener('Network.requestWillBeSent')
    addCDPRequestDataListener('Network.requestWillBeSentExtraInfo')
    addCDPRequestDataListener('Network.responseReceived')
    addCDPRequestDataListener('Network.responseReceivedExtraInfo')

    // clear any existing log entries
    const consolelog_info = {
        TYPE: 'console',
        VERSION: version,
        URL: original_url,
    }
    await overwriteFile(CONSOLELOG_PATH(page), JSON.stringify(consolelog_info) + '\n')

    // record console logs from page
    const appendConsoleLog = async (line) => {
        if (!line) return
        console_log.push(line)
        await fs.promises.appendFile(
            CONSOLELOG_PATH(page),
            line + '\n',
            'utf-8',
        )
    }

    page.on('console', async(message) =>
            await appendConsoleLog(`${message.type().toUpperCase()} ${message.location()} ${JSON.stringify(message.text())}`))
    page.on('pageerror', async (error) =>
            await appendConsoleLog(error.message || JSON.stringify(error)))
    page.on('requestfailed', async (request) =>
            await appendConsoleLog(`${request.failure()?.errorText} ${request.url() || JSON.stringify(request)}`))
    
    // set puppeteer options on page
    await client.send('Network.enable')                         // enable network tampering API
    await client.send('Emulation.clearDeviceMetricsOverride');  // clear timing statistics
    await client.send('Page.setDownloadBehavior', {
        behavior: 'allow',
        downloadPath: CHROME_DOWNLOADS_DIR,
    })

    // handled by stopMetadataRecording():
    // page.on('close', () => {
    //     try {
    //         page.off('request')
    //         page.off('console')
    //         page.off('pageerror')
    //         page.off('requestfailed')
    //         page.setRequestInterception(false)
    //     } catch(err) {
    //         // some versions of puppeteer have had race conditions here where page is already closed by now
    //         console.warn('[X] Error in page close handler', err)
    //     }
    // })

    return {original_url, client, redirects, traffic_log, console_log}
}

async function stopMetadataRecording(page, _page_state) {
    console.log('[🪝] Stopping CDP event hooks and request interception...')
    try {
        page.off('request')
        page.off('response')
        page.off('console')
        page.off('pageerror')
        page.off('requestfailed')
        page.off('hashchange')
        page.setRequestInterception(false)
        // page.tracing.stop()
    } catch(err) {
        // some versions of puppeteer have had race conditions here where page is already closed by now
        console.warn('[X] Error in page close handler', err)
    }
}

/********************** Human Behavior Emulation ******************************/

async function solveCaptchas(page, page_state, {timeout=90_000}={}) {

    // using puppeteer-extra-plugin-recaptcha auto-solver
    // await page.solveRecaptchas()

    // using 2captcha-solver extension auto-solver
    try {
        // console.log('[🕑] Waiting for CAPTCHA to appear...')
        await page.waitForSelector('.captcha-solver', {timeout: 5_000})

        console.log('[🤖] CAPTCHA challenge found, submitting to 2Captcha for solving...')
        await page.click('.captcha-solver')

        console.log(`[🧠] Waiting up to ${timeout/1000}s for CAPTCHA to be solved...`)
        await page.waitForSelector(`.captcha-solver[data-state="solved"]`, {timeout})

        console.log('[🔓] CAPTCHA solution retrieved from 2captcha.')
    } catch(err) {
        console.log('[☑️] No CATPCHA challenges found, site thinks we are human.')
    }
}

async function jiggleMouse(page, page_state, {timeout=600}={}) {
    console.log(`[🐁] Moving mouse around randomly for ${timeout/1000}s...`)

    const randomPoint = await getRandomPagePoint(page)
    const cursor = createCursor(page, randomPoint, true)

    cursor.toggleRandomMove(true)
    await wait(timeout/2);
    await cursor.moveTo({x: DEFAULT_VIEWPORT.width/2, y: DEFAULT_VIEWPORT.height/2});
    await wait(timeout/2);
    cursor.toggleRandomMove(false)
}

async function blockRedirects(page, {original_url}) {
    page.on('request', req => {
        if (req.isInterceptResolutionHandled()) return;

        // if it's a top-level navigation event to a new url
        if (req.isNavigationRequest() && req.frame() === page.mainFrame() && req.url() !== original_url) {
            req.abort('aborted');
            console.warn('[🟥] Blocked page attempt to naviage to new URL', req.url())
        } else {
            req.continue();
        }
    });
    // handled by stopMetadataRecording():
    // page.on('close', () => {
    //     page.off('request')
    //     page.setRequestInterception(false)
    // })
    await page.setRequestInterception(true);
}

async function blockJSExecution(page, _page_state) {
    console.warn('[🟥] Stopping all JS execution on page...')
    await page.evaluate(() => {
        debugger; 
    })
    // OR alternatively this (more buggy, breaks many sites):
    // const html = await page.content();
    // page.setJavaScriptEnabled(false);
    // await page.setContent(html, { waitUntil: 'networkidle0' }); // 4
}

async function scrollDown(page, _page_state, {timeout=120_000, scroll_delay=SCROLL_DELAY, scroll_distance=SCROLL_DISTANCE, scroll_limit=SCROLL_LIMIT}={}) {
    const starting_height = await page.evaluate('document.body.scrollHeight');
    let last_height = starting_height

    let scroll_count = 0;
    let scroll_position = scroll_count * scroll_distance
    // await page.bringToFront()

    // scroll to top
    await page.evaluate(() => { window.scrollTo({ top: 0, left: 0, behavior: 'smooth' }); });

    while ((scroll_count < scroll_limit) && ((scroll_delay * scroll_count) < timeout)) {
        console.log(`[⬇️] Scrolling down ${scroll_count}x 1000px... (${scroll_position}/${last_height})`)
        await page.evaluate((y_offset) => { window.scrollTo({ top: y_offset, left: 0, behavior: 'smooth' }); }, scroll_position);
        scroll_count++
        scroll_position = scroll_count * scroll_distance

        // check if any new content was added / if we are infiniscrolling
        let new_height = await page.evaluate('document.body.scrollHeight')
        const added_px = new_height - last_height
        if (added_px > 0) {
            console.log('[✚] Detected infini-scrolling...', `${last_height}+${added_px} => ${new_height}`)
        } else if (scroll_position >= new_height + scroll_distance) {
            // we've reached the bottom, condition isn't true until we've tried to go n+1 past the end (which is fine)
            if (scroll_count > 2)
                break
        }
        last_height = new_height
        
        // sleep 2s, perform the smooth scroll down by 1000px, and increment the counter
        await wait(scroll_delay);

        // facebook watch pages infiniscroll (more and more recommendations forever), stop them after 3 pages
        if (page._original_url.startsWith('https://www.facebook.com/watch/?v') && scroll_count > 3) break
    }

    // scroll to bottom
    if (scroll_position < last_height) {
        await page.evaluate(() => { window.scrollTo({ top: document.body.scrollHeight, left: 0, behavior: 'smooth' }); });
        await wait(scroll_delay)
        await page.evaluate(() => { window.scrollTo({ top: document.body.scrollHeight, left: 0, behavior: 'smooth' }); });
    }

    // Always wait an additional 2sec at the end for scroll animations / loading / rendering to settle down
    console.log('[📉] Reached bottom of the page.', `(${scroll_position}/${last_height})`)
    await wait(scroll_delay);
    await page.evaluate(() => { window.scrollTo({ top: 0, left: 0, behavior: 'smooth' }); });
    await wait(scroll_delay);

    return last_height
}

async function disableAnimations(page, _page_state) {
    console.log(`[⛄️] Disabling all animations using CSS override...`)

    // https://stackoverflow.com/questions/53167644/injecting-css-into-site-with-puppeteer
    const css_override = `*, *::before, *::after {
        -moz-animation: none !important;
        -moz-transition: none !important;
        animation: none !important;
        transition: none !important;
        caret-color: transparent !important;
    }`

    // inject override into current page
    await page.addStyleTag({content: css_override});

    // inject override into any subsequently navigated pages
    await page.evaluateOnNewDocument((css_override) => {
        const style_tag = document.createElement('style')
        style_tag.type = 'text/css'
        style_tag.innerHTML = css_override
        document.getElementsByTagName('head')[0].appendChild(style_tag)
    }, css_override);
}

async function expandComments(page, _page_state, {timeout=120_000, limit=15_000, delay=650}={}) {
    console.log(`[🗃️] Expanding up to ${limit} comments every ${delay}ms...`)
    
    // expand all <details> sections in Github READMEs, HedgeDoc pages, etc.
    await page.$$eval('pierce/article details', elem => {elem.open = true})           // expand Github README details sections
    await page.$$eval('pierce/div.js-discussion details:not(.details-overlay)', elem => {elem.open = true}) // expand Github issue discussion hidden comments
    await page.$$eval('pierce/.markdown-body details', elem => {elem.open = true})    // expand HedgeDoc Markdown details sections

    await page.exposeFunction('onHashChange', url => page.emit('hashchange', url));
    await page.evaluateOnNewDocument(() => {
        // @ts-ignore
        addEventListener('hashchange', (e) => onHashChange(location.href));
    });

    // Listen for hashchange events in node Puppeteer code.
    page.on('hashchange', url => console.log('Page tried to navigate to:', new URL(url)));


    const num_expanded = await page.evaluate(async ({timeout, limit, delay}) => {
        function getElementsByXPath(xpath, ctx?) {
            var results = [];
            var xpathResult = document.evaluate(
                xpath,                                                          // e.g. //*[text()='"+text+"'] 
                ctx || document,
                null,
                XPathResult.ORDERED_NODE_ITERATOR_TYPE,
                null
            );
            var node;
            while ((node = xpathResult.iterateNext()) != null) {
               results.push(node);
            }
            return results;
        }

        let num_expanded = 0
        const getLoadMoreLinks = () => [
            // find all the buttons/links to expand collapsed/hidden/lazy-loaded content 
            ...document.querySelectorAll('faceplate-partial[loading=action]'),  // new reddit
            ...document.querySelectorAll('a[onclick^="return morechildren"]'),  // old reddit show more replies
            ...document.querySelectorAll('a[onclick^="return togglecomment"]'), // old reddit show hidden replies
            // ...document.querySelectorAll('a.js-show-link'),                     // stack overflow comments show more (TODO: make this only work on SO)
            // ...document.querySelectorAll('a.morelink'),                         // HackerNews profile show more (TODO: make this only work on HN)
            // ...getElementsByXPath("//*[text()~='View \d+ replies']"),        // facebook comment expander
            ...getElementsByXPath("//*[text()='Show more replies']"),           // twitter infiniscroll expander
            ...getElementsByXPath("//*[text()='Show replies']"),                // twitter replies expander
        ]
        const wait = (ms) => new Promise(res => setTimeout(res, ms))

        let load_more_links = getLoadMoreLinks()
        while (load_more_links.length) {
            console.log('Expanding comments...', load_more_links.length)
            for (const link of load_more_links) {
                link.scrollIntoView({behavior: 'smooth'})
                if (link.slot == 'children') {
                    continue
                    // patch new reddit "More replies" links that would open in a new window to display inline instead
                    // const comment_id = link.src.split('?')[0].split('/').at(-1)
                    // link.slot = `children-${comment_id}-0`
                    // link.__alwaysShowSlot = false
                }
                // click the "More replies" button
                link.click()
                num_expanded++
                await wait(delay)
                const time_elapsed = num_expanded * delay
                if ((num_expanded > limit) || (time_elapsed > timeout))
                    return num_expanded
            }
            load_more_links = getLoadMoreLinks()
        }
        return num_expanded
    }, {timeout, limit, delay});

    page.off('hashchange')

    if (num_expanded) {
        console.log(`[🗃️] Expanded ${num_expanded} comments...`)
        
        // scroll to bottom, then back up to top
        const final_height = await page.evaluate('document.body.scrollHeight');
        await page.evaluate((top) => { window.scrollTo({ top, left: 0, behavior: 'smooth' }); }, final_height + 1000);
        await wait(delay);
        await page.evaluate(() => { window.scrollTo({ top: 0, left: 0, behavior: 'smooth' }); });
        await wait(delay);
    }

}

async function submitForm(page, _page_state, {timeout=5_000}={}) {
    try {
        await page.waitForSelector('form button[type=submit]', {timeout: 1_500});
        console.log('[☑️] Submitting form...')
        await page.click('form button[type=submit]')
        await page.waitForNavigation({timeout});
        await page.goBack();
    } catch (err) {
        // no form found
    }
}

// TODO: add an evasion to set navigator.connection.rtt = 365 (0 = detectable as headless)

/******************************************************************************/
/******************************************************************************/

/**************** Extension-Based Archive Output Tasks ************************/

async function saveSinglefile(page, {main_response, extensions}) {
    const extension = extensions.filter(({name}) => name === 'singlefile')[0]
    if (!extension.version) throw 'Could not find Singlefile extension ID, is it installed?'

    const url = await page.url() || main_response.url()
    if (URL_SCHEMES_IGNORED.includes(url.split(':')[0])) return null

    // get list of existing past files in downloads/* to ignore
    const files_before = new Set(
        (await fs.promises.readdir(CHROME_DOWNLOADS_DIR))
            .filter(fn => fn.endsWith('.html'))
    );

    const out_path = SINGLEFILE_PATH(page)

    console.log(`[🛠️] Saving Singlefile HTML using extension (${extension.id})...`.padEnd(82+1), prettyPath(CHROME_DOWNLOADS_DIR))
    await page.bringToFront()     // action button acts on the foreground tab, so it has to be in front :(
    await extension.dispatchAction()
    let files_new = []

    const check_delay = 3_000
    for (const _try in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) {
        await wait(check_delay)

        const files_after = (await fs.promises.readdir(CHROME_DOWNLOADS_DIR)).filter(fn => fn.endsWith('.html'));
        files_new = files_after.filter(file => !files_before.has(file))

        if (files_new.length == 0) {
            // console.warn(`    ...waiting for Singlefile to write HTML into ${CHROME_DOWNLOADS_DIR}...`)
            continue
        }
        // iterate through new downloads and find a matching .html containing our page's URL in the header
        for (const file of files_new) {
            const dl_path = path.join(CHROME_DOWNLOADS_DIR, file)
            const dl_text = await fs.promises.readFile(dl_path, 'utf-8')
            const dl_header = dl_text.split('meta charset')[0]
            if (dl_header.includes(`url: ${url}`)) {
                /// dont need this check anymore as now all output is versioned:
                // if (fs.existsSync(out_path)) {
                //     const {size: existingSize} = await fs.promises.stat(out_path)
                //     const {size: newFileSize} = await fs.promises.stat(dl_path)
                //     if (newFileSize < existingSize) {
                //         console.log(`[🗑️] Discarding singlefile output (${file}) as it's smaller than existing ${out_path}...`)
                //         await fs.promises.rm(dl_path)
                //         return out_path
                //     }
                // }
                console.log(`[✍️] Moving Singlefile download from ${file}...`.padEnd(82), prettyPath(out_path))
                await fs.promises.rename(dl_path, out_path)
                return out_path
            }
        }
    }

    console.warn(`[❌] Couldn't find matching Singlefile HTML in ${CHROME_DOWNLOADS_DIR} after waiting ${(check_delay*10)/1000}s:`, files_new.join(', '))
    return null
}

async function saveArchiveWebPage(page, {extensions}, {timeout=30_000}={}) {
    // TODO: waiting on them to expose commands so we can generate .wacz easily
    // https://github.com/webrecorder/archiveweb.page/issues/207
    // ...
    const browser = await page.browser()
    const extension = extensions.filter(({name}) => name === 'archivewebpage')[0]
    await page.bringToFront()
    await extension.dispatchPopup()
    await extension.dispatchAction()
    const popup = await browser.waitForTarget(
        target => target.url().toString().startsWith(`chrome-extension://${extension.id}/popup.html`),
        {timeout: 5_000},
    )
    await page.bringToFront()

    // await puppeteer.Locator.race([
    //     popup.locator('::-p-aria(Start With Autopilot)'),
    //     popup.locator('wr-popup-viewer >>>> input'),
    //     popup.locator(':scope >>> input')
    // ])
    // .setTimeout(timeout)
    // .click({
    //   offset: {
    //     x: 7.7265625,
    //     y: 7.203125,
    //   },
    // });

    // @ts-ignore
    await puppeteer.Locator.race([
        popup.locator('wr-popup-viewer >>>> div.status-row > p'),
        popup.locator(':scope >>> div.status-row > p'),
        popup.locator('::-p-text(Recording: \n)')
    ]).setTimeout(timeout).click({
      delay: 733.3000000007451,
      offset: {
        x: 293,
        y: 13.5,
      },
    })

    await wait(8_000)

    // @ts-ignore
    await puppeteer.Locator.race([
        popup.locator('wr-popup-viewer >>>> div:nth-of-type(2) > button > span:nth-of-type(2)'),
        popup.locator(':scope >>> div:nth-of-type(2) > button > span:nth-of-type(2)'),
        popup.locator('::-p-text(Stop)')
    ]).setTimeout(timeout).click({
      offset: {
        x: 7.859375,
        y: 23.203125,
      },
    });

    return null
}

async function savePocket(page, {extensions}) {
    const browser = await page.browser()
    const extension = extensions.filter(({name}) => name === 'pocket')[0]
    if (!extension.version) throw 'Could not find Pocket extension ID, is it installed?'

    console.log(`[🛠️] Saving URL to Pocket API using extension (${extension.id})...`, 'https://getpocket.com/saves')
    await page.bringToFront()    // action button acts on the foreground tab, so it has to be in front
    await extension.dispatchAction()
    try {
        const login_window = await browser.waitForTarget(
            target => target.url().toString().startsWith('https://getpocket.com/'),
            {timeout: 3_000},
        )
        // login window will open if pocket is not signed-in
        if (login_window) return false
    } catch(e) {
        // no new window should open if it saves correctly
        return true
    }
}

/***************** Synchronous Archive Output Tasks ***************************/

async function saveScreenrecording(page, page_state, {save_gif=true}={}) {
    if (page_state.recorder) {
        const duration = Date.now() - page_state.start_ts
        console.log(`[🎥] Saving screen-recording video (${duration/1000}s)...`.padEnd(82), prettyPath(SCREENRECORDING_PATH(page)))
        const recorder = page_state.recorder
        page_state.recorder = null
        await recorder.stop()

        // create symlink for legacy path
        const snap_dir = page_state.snapshot_dir
        const legacy_path = path.join(snap_dir, 'media', 'screenrecording.mp4')
        await overwriteSymlink(SCREENRECORDING_PATH(page), legacy_path, {relative: snap_dir, search_limit: snap_dir})

        // // remove duplicate frames (white frames at start while it loads + static image at end)
        // const video_path = SCREENRECORDING_PATH(page)
        // const short_path = video_path.replace('.mp4', '.short.mp4')
        // try {
        //     await exec(
        //         // create a shortened video starting from 0:02s to 0:01s with duplicate frames removed (can look jumpy sometimes)
        //         `ffmpeg -ss 2 -sseof -1 -y -i ${video_path} -vf mpdecimate,setpts=N/FRAME_RATE/TB ${short_path}`
        //     )
        // } catch(err) {
        //     console.log('[❌] Failed to shorten screenrecording.mp4')
        // }

        // convert video to GIF
        if (save_gif) {
            try {
                const BIN_NAME = '/Volumes/NVME/Users/squash/bin/ffmpeg'
                const child = child_process.spawn(
                    BIN_NAME,
                    [
                        '-hide_banner',
                        '-loglevel', 'error',
                        '-ss', '3',
                        '-t', '10',
                        '-y',
                        '-i', SCREENRECORDING_PATH(page),
                        '-vf', "fps=10,scale=1024:-1:flags=bicubic,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                        '-loop', '0',
                        SCREENRECORDGIF_PATH(page),
                    ],
                    {
                        cwd: path.dirname(SCREENRECORDING_PATH(page)),
                        timeout: 60_000,
                        // stdio: [null, 'pipe', 'pipe'],
                        stdio: 'ignore',
                        detached: true,                          // run in background, don't block on response
                    },
                )
                await blockUntilExists(SCREENRECORDGIF_PATH(page), {min_bytes: 100, timeout: 40_000})
                console.log(`[🎥] Saved screen-recording GIF with ffmpeg pid=${child.pid} (${duration/1000}s)...`.padEnd(82), prettyPath(SCREENRECORDGIF_PATH(page)))

                const snap_dir = page_state.snapshot_dir
                const legacy_path = path.join(snap_dir, 'media', 'screenrecording.gif')
                await overwriteSymlink(SCREENRECORDGIF_PATH(page), legacy_path, {relative: snap_dir, search_limit: snap_dir})
            } catch(err) {
                console.log('[❌] Failed to convert video to GIF:', err)
            }
        }

        return SCREENRECORDING_PATH(page)
    }
    return null
}

async function saveScreenshot(page, _page_state, {aspect_ratio=SCREENSHOT_ASPECT_RATIO, width=null, height=null, jpg_width=1440, jpg_quality=90, timeout=30_000}={}) {
    try {await fs.promises.unlink(SCREENSHOT_PATH(page))} catch(err) {}
    
    // setup width and height
    width = width || DEFAULT_VIEWPORT.width
    assert((typeof width === 'number') && width > 200)
    height = height || Math.floor(width/aspect_ratio)
    assert((typeof height === 'number') && height > 200)
    
    console.log(`[📸] Saving full-page screenshot (${width}x${height}px)...`.padEnd(82), prettyPath(SCREENSHOT_PATH(page)))

    // set width, height, and deviceScale factor: https://github.com/puppeteer/puppeteer/issues/1576
    await page.setViewport({ ...DEFAULT_VIEWPORT, width, height, deviceScaleFactor: 2})
    await page.bringToFront()
    await wait(1_250)       // page takes a sec settle after foregrounding and viewport update

    // take lossless fullpage screenshot of 1920x1440+px (4:3+) -> ./screenshot.png
    await page.screenshot({ path: SCREENSHOT_PATH(page), fullPage: true, type: 'png' })
    
    // wait for the screenshot to be created, then set the viewport to the next size
    await blockUntilExists(SCREENSHOT_PATH(page), {min_bytes: 100, timeout})
    await wait(6_000)       // puppeteer takes a while to finish writing png data when fullPage: true
    
    const jpg_height = Math.floor(jpg_width/aspect_ratio)
    await page.setViewport({ ...DEFAULT_VIEWPORT, width: jpg_width, height: jpg_height, deviceScaleFactor: 2})
    await wait(1_250)       // page takes a sec settle after foregrounding and viewport update

    // WARNING: make sure you never try to create two screenshots at the same time (especially not fullpage screenshots)
    // thats why there are all these delays here.
    // screenshot creation messes up the whole viewport while it's running,
    // and it writes bad/white empty screenshots if you try to make more than one concurrently

    // take compressed screenshot of jpg_width*jpg_height (4:3) -> ./screenshot.jpg
    await page.screenshot({
        path: SCREENSHOT_JPG_PATH(page),
        type: 'jpeg',
        quality: jpg_quality,
        clip: {
            x: 0,
            y: 0,
            width: jpg_width,
            height: jpg_height,
        },
        captureBeyondViewport: false,
    });
    await blockUntilExists(SCREENSHOT_JPG_PATH(page), {min_bytes: 100, timeout: timeout/2})
    console.log(`[📸] Saved screenshot as screenshot.jpg (${jpg_width}x${jpg_height}px)...`.padEnd(82), prettyPath(SCREENSHOT_JPG_PATH(page)))

    // reset viewport back to defaults
    await wait(1_250)
    await page.setViewport(DEFAULT_VIEWPORT)

    // ALTERNATIVE METHOD based on cropping fullpage png and converting to jpg manually:
    // import {PNG} from 'pngjs';
    // import jpeg from 'jpeg-js';
    // setTimeout(async () => {
    //     try {
    //         const screenshot_png = SCREENSHOT_PATH(page);
    //         const screenshot_jpg = SCREENSHOT_JPG_PATH(page)
    //         const jpg_max_height = height
    //         const jpg_quality = quality; // Adjust the quality as needed (0-100)

    //         fs.createReadStream(screenshot_png)
    //             .pipe(new PNG())
    //             .on('parsed', function () {
    //                 const width = this.width;
    //                 const height = this.height;
            
    //                 let cropped_height = height;
    //                 if (height > jpg_max_height) {
    //                   cropped_height = jpg_max_height;
    //                 }
            
    //                 const cropped_bytes = new Uint8Array(width * cropped_height * 4);
    //                 for (let y = 0; y < cropped_height; y++) {
    //                   for (let x = 0; x < width; x++) {
    //                     const idx = (width * y + x) << 2;
    //                     cropped_bytes[idx] = this.data[idx];
    //                     cropped_bytes[idx + 1] = this.data[idx + 1];
    //                     cropped_bytes[idx + 2] = this.data[idx + 2];
    //                     cropped_bytes[idx + 3] = this.data[idx + 3];
    //                   }
    //                 }
            
    //                 const jpeg_obj = {
    //                   data: cropped_bytes,
    //                   width: width,
    //                   height: cropped_height,
    //                 };
            
    //                 const jpeg_bytes = jpeg.encode(jpeg_obj, jpg_quality);
    //                 fs.writeFileSync(screenshot_jpg, jpeg_bytes.data);
    //                 console.log(`[📸] Saved screenshot as screenshot.jpg (${width}x${jpg_max_height}px)...`.padEnd(82), prettyPath(SCREENSHOT_JPG_PATH(page)))
    //             });
    //     } catch(err) {
    //         console.error('[X] Error while generating JPG screenshot', SCREENSHOT_JPG_PATH(page), err)
    //     }
    // }, DELAY_BEFORE_JPG_CONVERSION)  

    // ALTERNATIVE METHOD TO WRITE SCREENSHOT JPG:
    // await wait(5_000)  // puppeteer takes a while to finish writing png data when fullPage: true
    // if ((await page.evaluate('document.body.scrollHeight')) > max_height) {
    //     // if page exceeds max_height, save additional cropped screenshot as screenshot.top.png
    //     // (needed b.c. uncropped screenshot may have insane 1:20+ aspect ratio that is hard to use elsewhere)
    //     await page.screenshot({ path: SCREENSHOT_JPG_PATH(page), type: 'jpg', quality: 100})
    //     await wait(1_000)  // page takes a sec settle after a screenshot
    // }

    return SCREENSHOT_PATH(page)
}

async function savePDF(page, _page_state, {timeout=30_000}={}) {
    const url = page.url() || 'about:blank'
    if (URL_SCHEMES_IGNORED.includes(url.split(':')[0])) return null

    const out_path = PDF_PATH(page)
    console.log(`[📓] Saving print-as-PDF export...`.padEnd(82), prettyPath(out_path))
    await page.bringToFront()
    try {await fs.promises.unlink(PDF_PATH(page))} catch(err) {}

    // await page.emulateMediaType('screen')           // print as "@media(screen) instead of @media(print)"

    // page.createPDFStream lets us to save larger PDFs than page.pdf() before crashing
    // (streams to disk in chunks instead of all at once)
    const pdf_stream = await page.createPDFStream({
        timeout: timeout,
        printBackground: true,
        outline: true,
        tagged: true,
        format: 'A4',
        displayHeaderFooter: false,
        // margin: { top: '0.5cm', right: '1cm', bottom: '0.8cm', left: '1cm' },
    })
    const reader = pdf_stream.getReader()

    // iterate through reader and append chunks to out_path
    await fs.promises.rm(out_path, {force: true})
    let num_bytes = 0
    let error = '0 bytes written'
    try {
        while (true) {
            const {done, value} = await reader.read()
            if (done) break;
            await fs.promises.appendFile(out_path, value)
            num_bytes += value.length;
        }
    } catch(error) {
        num_bytes = 0
    }

    if (!num_bytes) {
        console.warn('[❌] Failed to save PDF', JSON.stringify(error, null, 4))
        await fs.promises.rm(out_path, {force: true})
        return null
    }

    return out_path
}

async function inlineShadowDOM(page, _page_state, {limit=100_000}={}) {
    console.log(`[😎] Replacing Shadow DOM elements with inline HTML...`)

    try {
        const num_replaced = await page.evaluate((limit) => {
            let num_replaced = 0

            // Returns HTML of given shadow DOM.
            const getShadowDomHtml = (shadowRoot) => {
                let shadowHTML = '';
                for (const el of shadowRoot.childNodes) {
                    shadowHTML += el.nodeValue || el.outerHTML;
                }
                return shadowHTML;
            };

            // Recursively replaces shadow DOMs with their HTML.
            const replaceShadowDomsWithHtml = (rootElement) => {
                if (num_replaced > limit) return
                for (const el of rootElement.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        replaceShadowDomsWithHtml(el.shadowRoot);
                        el.innerHTML += getShadowDomHtml(el.shadowRoot);
                    }
                }
                num_replaced++
            };

            replaceShadowDomsWithHtml(document.body);

            return num_replaced
        }, limit)
        // console.log('    √ replaced', num_replaced, 'Shadow DOM trees')
    } catch(err) {
        console.log('[⚠️] Inlining Shadow DOM failed', err)
    }
}

async function saveAIQualityAssuranceResult(page, {original_url, version}) {
    console.log(`[🧠] Analyzing screenshot with GPT-4o for QA checks...`.padEnd(82), prettyPath(AIQA_PATH(page)))
    
    let screenshot_path = SCREENSHOT_PATH(page)
    const screenshot_cropped_path = SCREENSHOT_JPG_PATH(page)

    if (fs.existsSync(screenshot_cropped_path)) {
        // screenshot is too tall to pass to openai, send cropped version instead
        screenshot_path = screenshot_cropped_path
    }
    try {
        await blockUntilExists(screenshot_path, {min_bytes: 100, timeout: 7_500})
    } catch (err) {
        console.warn('[❌] Failed to send screenshot to GTP-4o for analysis, no screenshot.{png,jpg} exists', err)
        return null
    }
    var stdout = ''
    var stderr = ''
    let result = null
    const PYTHON_BIN = path.join(__dirname, '.venv/bin/python')
    const SCRIPT_PATH = path.join(__dirname, 'ai_qa.py')
    await blockUntilExists(PYTHON_BIN, {min_bytes: 1, timeout: 250})
    await blockUntilExists(SCRIPT_PATH, {min_bytes: 1, timeout: 250})

    try {
        var {stdout, stderr} = await exec(
            `${PYTHON_BIN} ${SCRIPT_PATH} --attach '${screenshot_path}'`
        )
        result = JSON.parse(stdout.toString())
        if (!result) throw 'Got empty result!'
        result = {
            TYPE: 'aiqa',
            VERSION: version,
            URL: original_url,
            ...result,
        }
    } catch(parse_err) {
        console.warn('[❌] Failed to get OpenAI analysis for screenshot.png', parse_err, stderr)
    }
    if (!(result || stdout)) {
        return null
    }
    await overwriteFile(
        AIQA_PATH(page),
        result || stdout.toString(),
    )
 
    

    return result
}

async function saveYTDLP(page, {original_url, version}, {max_size='750m'}={}) {
    console.log(`[🎥] Saving media with YT-DLP (<=${max_size})...`.padEnd(82), prettyPath(YTDLP_PATH(page)))

    await fs.promises.mkdir(YTDLP_PATH(page), {recursive: true})

    const cwd = YTDLP_PATH(page)
    const bin_name = 'yt-dlp'
    const timeout = 300_000              // 5min timeout
    const args = [
        '--restrict-filenames',
        '--trim-filenames', '128',
        '--write-description',
        '--write-info-json',
        '--write-annotations',
        '--write-thumbnail',
        '--no-call-home',
        '--write-sub',
        '--write-auto-subs',
        '--convert-subs=srt',
        '--yes-playlist',
        '--continue',
        '--no-abort-on-error',
        '--ignore-errors',
        '--geo-bypass',
        '--add-metadata',
        `--format=(bv*+ba/b)[filesize<=${max_size}][filesize_approx<=?${max_size}]/(bv*+ba/b)`,
        '--no-check-certificate',
        '--no-progress',
        // `--cookies=${COOKIES_TXT_PATH}`,   // using logged in cookies actually makes it fail more often, not sure why
        original_url,
    ]

    const {getResult, ...exec_info} = await saveExecResult(bin_name, args, {original_url, version}, {cwd, timeout})

    return {getResult, ...exec_info}
}

async function saveGALLERYDL(page, {original_url, version}) {
    console.log(`[🎥] Saving photos with gallery-dl...`.padEnd(82), prettyPath(GALLERYDL_PATH(page)))

    await fs.promises.mkdir(GALLERYDL_PATH(page), {recursive: true})

    const cwd = GALLERYDL_PATH(page)
    const bin_name = 'gallery-dl'
    const timeout = 300_000              // 5min timeout
    const args = [
        '--verbose',
        '--write-metadata',
        '--write-infojson',
        '--write-tags',
        '--sleep=1.5-2.5',
        `--cookies=${COOKIES_TXT_PATH}`,
        // '--no-check-certificate',
        // `--directory=media`,
        original_url,
    ]

    const {getResult, ...exec_info} = await saveExecResult(bin_name, args, {original_url, version}, {cwd, timeout})

    return {getResult, ...exec_info}
}

// async function saveWget(page, {original_url, version}) {
//     console.log(`[⎒] Saving wget site clone...`.padEnd(82), prettyPath(WGET_PATH(page)))

//     const args = [
//         // ...
//     ]
 
//     spawn(
//         'wget',
//         [
//             ...args,
//             original_url,
//         ],
//         {
//             cwd: WGET_PATH(page),
//             detached: true,         // run in background, don't block on response
//             stdio: 'ignore',
//             timeout: 300_000,       // 5min timeout
//         },
//     )

//     return {path: WGET_PATH(page)}
// }

/**************** Asynchronous Archive Output Tasks ***************************/

type FaviconCandidate = {
    url: string,
    basename: string,
    extension: string,
    expected_mimetype: string,
}

const faviconFromDomain = (url) => {
    // https://auth:pass@t.co:1234/a/bc123 -> https://auth:pass@t.co:1234/favicon.ico
    const url_origin = (new URL(url)).origin
    return {
        url: url_origin ? `${url_origin}/favicon.ico` : null,
        basename: 'favicon',
        extension: undefined,                     // auto-detect extension at download time in case it redirects us to a png
        expected_mimetype: 'image/',              // only accept image/* to avoid saving html/txt error reponses as icon
    } as FaviconCandidate
}

const faviconFromGoogle = (url, size=256) => {
    // https://auth:pass@t.co:1234/a/bc123 -> https://www.google.com/s2.favicons?domain=t.co
    const domain = url && (new URL(url)).hostname
    return {
        url: domain?.includes('.') ? `https://www.google.com/s2/favicons?sz=${size},domain=${domain}` : null,
        basename: 'google_favicon',
        extension: 'png',
        expected_mimetype: 'image/png',           // google always provides PNGs in response
    } as FaviconCandidate
}

const faviconFromHtml = async (page) => {
    // <link rel="icon" src="https://example.com/static/images/favicon.png"/> -> https://example.com/static/images/favicon.png
    let url
    try {
        url = await page.$eval('link[rel*="icon"]', (elem) => elem?.href)
        if (!url || !url.includes('://'))
            url = null
    } catch(err) {
        url = null
        // console.warn('Failed to find favicon tag in html', JSON.stringify(err, null, 4))
    }

    return {
        url,
        basename: 'favicon',
        extension: undefined,                    // auto-detect extension at download time
        expected_mimetype: 'image/',             // accept any image/* mimetype at download time
    } as FaviconCandidate
}

type FaviconResult = {
    url: string,
    num_bytes: number,
    abspath?: string,
    dir?: string,
    filename?: string,
    mimeType?: string,
}

async function saveFavicon(page, {original_url, main_response, version}) {
    const dir = path.dirname(FAVICON_PATH(page))
    const response_url = main_response?.url()

    const favicon_downloads_to_try: {[key: string]: FaviconCandidate} = unique([
        await faviconFromHtml(page),
        faviconFromDomain(response_url),
        faviconFromDomain(original_url),
        faviconFromGoogle(response_url),
        faviconFromGoogle(original_url),
    ].filter(({url}) => url), 'url')

    const browser = await page.browser()

    // let logs = []
    // let errors = []
    let output_files: {[key: string]: FaviconResult} = {}

    for (const download_options of Object.values(favicon_downloads_to_try)) {
        let result: FaviconResult = {num_bytes: 0, url: download_options.url}
        // {url, num_bytes, abspath, dir, filename, basename, extension, mimeType}
        try {
            // try getting it with node-fetch first
            const response = await fetch(download_options.url) as Response
            const file_options = await detectFilename({...download_options, response, dir})
            if (response.headers.get("content-length")) {
                const favicon_stream = Readable.fromWeb(response.body as any)
                await overwriteFile(file_options.abspath, favicon_stream)
                result = {
                    ...file_options,
                    num_bytes: parseInt(response.headers.get("content-length") || '0'),
                    mimeType: response.headers.get("content-type"),
                }
            } else {
                throw 'Failed to download favicon with fetch()'
            }
        } catch(err) {
            // console.warn('[!] Failed to get favicon with node-fetch', err)
            // fallback to getting it by opening a new browser tab
            result = await download({...download_options, browser, dir, page})
        }

        // logs.push(...(result.logs || []))
        // errors.push(...(result.errors || []))

        if (result.num_bytes) {
            console.log(`[🌠] Saving page favicon (${result.url.substring(0, 35)}... ${result.mimeType})...`.padEnd(82), prettyPath(result.abspath))
            output_files[result.filename] = result
            break   // break here stops after the first successful download, comment out to keep going instead
        }
    }
    const output_file = Object.values(output_files).sort(file => file.num_bytes).at(-1)
    const favicon_info = {
        TYPE: 'favicon',
        VERSION: version,
        URL: original_url,
        succeeded: !!output_file,
        // stdout: JSON.stringify(logs),
        // stderr: JSON.stringify(errors),
        favicon_url: output_file?.url,
        favicon_urls: Object.keys(favicon_downloads_to_try),
        favicon_files: Object.keys(output_files).map(fname => fname.replace(dir, '.')),
        favicon_filename: output_file?.filename,
        favicon_num_bytes: output_file?.num_bytes,
    }
    await overwriteFile(FAVICON_PATH(page), favicon_info)

    return favicon_info
}

async function saveTitle(page, {original_url, version}) {
    const title_from_browser = (await page.title()) || null
    const title_from_js = await page.evaluate(() => document?.title || null)
    const title_from_html = await page.evaluate(() => document?.querySelector('title')?.innerText || null)
    const title_from_og = await page.evaluate(() => document?.querySelector('meta[property="og:title"]')?.getAttribute('content') || null)

    // best guess at best title = longest title
    const title = ([title_from_html, title_from_og, title_from_js, title_from_browser]
        .filter(title => title)
        .sort((a, b) => b.length - a.length)[0] || '')
        .replaceAll('\n', ' ')

    if (title?.length) {
        console.log(`[📗] Saving page title (${title.substring(0, 40)})...`.padEnd(82), prettyPath(TITLE_PATH(page)))
        await overwriteFile(TITLE_PATH(page), title)
    }

    const title_info = {
        TYPE: 'title',
        VERSION: version,
        URL: original_url,
        title,
        title_from_html,
        title_from_og,
        title_from_js,
        title_from_browser,
    }
    const title_json_path = TITLE_PATH(page).replace('.txt', '.json')
    await overwriteFile(title_json_path, title_info)

    return title_info
}

async function saveRaw(page, {main_response}) {
    const response = main_response
    if (!response) {
        console.warn('[⚠️] Failed to save page RAW bytes, main_response is null', response)
    }
    const dir = RAW_PATH(page)
    await fs.promises.mkdir(dir, {recursive: true})

    const {url, abspath, mimeType} = await detectFilename({page, response, dir})

    console.log(`[🔟] Saving raw response bytes (${mimeType})...`.padEnd(82), prettyPath(abspath))

    await download({page, response, abspath})
    return abspath
}

async function saveSourceMaps(page, {original_url, version}) {
    console.log(`[🐛] Saving source maps to ./responses/all/*.{js,css}.map...`)

    const response_index_path = path.join(RESPONSES_PATH(page), 'index.jsonl')
    const response_index = await fs.promises.readFile(response_index_path, 'utf-8')

    const urls_to_download = []

    for (const response of response_index.split('\n')) {
        try {
            const {url, extension} = JSON.parse(response)
            if (['css', 'js'].includes(extension?.toLowerCase())) {
                urls_to_download.push(url + '.map')
            }
        } catch(err) { continue }
    }

    // TODO: fix this, it needs to both after stopSavingMetadata and before stopSavingMetadata
    // fix is to use traffic_log to get response url list instead of waiting for index.jsonl to be created
    await page.evaluate(async (urls_to_download) => {
        const promises = []
        for (const sourcemap_url in urls_to_download) {
            promises.push(fetch(sourcemap_url))
        }
        return Promise.allSettled(promises)
    }, urls_to_download)

    return {
        TYPE: 'sourcemaps',
        URL: original_url,
        VERSION: version,
        sourcemaps: urls_to_download,
    }
}

async function saveRequests(page, {original_url, version, traffic_log}) {
    console.log(`[📼] Saving requests log (${Object.keys(traffic_log).length})...`.padEnd(82), prettyPath(REQUESTS_PATH(page)))

    const requests_info = {
        TYPE: 'requests',
        VERSION: version,
        URL: original_url,
        requests: traffic_log,
    }

    await overwriteFile(REQUESTS_PATH(page), requests_info)

    return requests_info
}

async function saveRedirects(page, {original_url, main_response, traffic_log, redirects, version}) {
    const main_request_id = Object.keys(traffic_log).filter(id => !id.includes('.'))[0]
    const main_response_traffic = traffic_log[main_request_id] || {}

    const url_from_browser = await page.url() || null
    const url_from_request = (
        main_response?.request()?.url()
        || main_response_traffic['Network.requestWillBeSent']?.request?.url
        || null)
    const url_from_response = (
        main_response?.url()
        || main_response_traffic['Network.responseReceived']?.main_response?.url
        || null)

    const http_redirects = 
        Object.values(traffic_log)
            .filter(event => event['Network.requestWillBeSent']?.redirectResponse)
            .map(event => event['Network.requestWillBeSent'])
            .map(requestWillBeSent => ({
                url: requestWillBeSent.request.url,
                src: requestWillBeSent.redirectResponse.url,
                status: requestWillBeSent.redirectResponse.status,
                loaderId: requestWillBeSent.loaderId,
                requestId: requestWillBeSent.requestId,
                wallTime: requestWillBeSent.wallTime,
                initiator: requestWillBeSent.initiator,
                isMainFrame: (requestWillBeSent.loaderId == main_request_id),
            }))
    
    const url_parsed = new URL(url_from_response || url_from_request || url_from_browser)

    const redirects_info = {
        TYPE: 'redirects',
        VERSION: version,
        URL: original_url,
        url_parsed,
        url_from_request,
        url_from_response,
        url_from_browser,
        redirects_from_browser: redirects,
        redirects_from_http: http_redirects,
    }
    console.log(`[🔗] Saving page redirects log (${http_redirects.length})...`.padEnd(82), prettyPath(REDIRECTS_PATH(page)))

    await overwriteFile(REDIRECTS_PATH(page), redirects_info)

    return redirects_info
}

async function saveHeaders(page, {original_url, version, traffic_log}) {
    const main_request_id = Object.keys(traffic_log).filter(id => !id.includes('.'))[0]
    const main_response_traffic = traffic_log[main_request_id] || {}

    // combine base request with browser-added request headers
    const request = {...main_response_traffic['Network.requestWillBeSent']?.request}
    const request_extra_headers = main_response_traffic['Network.requestWillBeSentExtraInfo']?.headers || {}
    request.headers = {...request.headers, ...request_extra_headers}

    // combine base response with browser-added response headers
    const response = {...main_response_traffic['Network.responseReceived']?.response}
    const response_extra_headers = main_response_traffic['Network.responseReceivedExtraInfo']?.headers || {}
    response.headers = {...response.headers, ...response_extra_headers}

    const headers_info = {
        TYPE: 'headers',
        VERSION: version,
        URL: original_url,
        request,
        response,
    }

    const num_headers = Object.keys({...request.headers, ...response.headers}).length
    if (num_headers) {
        console.log(`[👾] Saving main request & response headers (${num_headers})...`.padEnd(82), prettyPath(HEADERS_PATH(page)))
        await overwriteFile(HEADERS_PATH(page), headers_info)
    }

    return headers_info
}
 
async function saveSSL(page, {original_url, version, traffic_log}) {
    const main_request_id = Object.keys(traffic_log).filter(id => !id.includes('.'))[0]
    const main_response_traffic = traffic_log[main_request_id] || {}

    const relevant_response_keys = [
        'url',
        'status',
        'mimeType',
        'connectionReused',
        'remoteIPAddress',
        'remotePort',
        'fromServiceWorker',
        'encodedDataLength',
        'protocol',
        'alternateProtocolUsage',
        'securityState',
        'securityDetails',
    ]
    let ssl_info = Object.entries(main_response_traffic['Network.responseReceived']?.response || {})
        .reduce((obj, [key, val]) => {
            if (relevant_response_keys.includes(key)) {
                obj[key] = val
            }
            return obj
        }, {}) as any

    // TODO: parse SSL certificate sha256 hash from chrome://system/#chrome_root_store
    // const ssl_certificate = await client.send('Network.getCertificate', {origin: original_url})
    // ssl_info.sslCertSha256 = '<unknown>'

    ssl_info = {
        TYPE: 'ssl',
        VERSION: version,
        URL: original_url,
        ...ssl_info,
    }

    if (Object.keys(ssl_info).length-3) {
        console.log(`[🔏] Saving page SSL details (${ssl_info?.securityDetails?.protocol})...`.padEnd(82), prettyPath(SSL_PATH(page)))
        await overwriteFile(SSL_PATH(page), ssl_info)
    }

    return ssl_info
}


async function saveDOM(page, {original_url, version}) {
    const html = await page.content();
    console.log(`[📖] Saving DOM dump (${html.length})...`.padEnd(82), prettyPath(DOM_PATH(page)))
    const html_with_header = 
        `<!-- Saved by ArchiveBox TYPE=dom VERSION=${version} URL=${original_url} -->\n${html}`
    await overwriteFile(DOM_PATH(page), html_with_header)
    return DOM_PATH(page)
}

async function saveBodyText(page, _page_state) {
    const innerText = await page.evaluate(() => document?.body?.innerText);

    if (innerText?.length) {
        console.log(`[📃] Saving body text (${innerText.length})...`.padEnd(82), prettyPath(BODYTEXT_PATH(page)))
        await overwriteFile(BODYTEXT_PATH(page), innerText)
    }

    // // alternative method: emulate Ctrl+A, Ctrl+C (sometimes gets more than body.innerText)
    // const innerText = await page.$eval('*', (el) => {
    //     const selection = window.getSelection();
    //     const range = document.createRange();
    //     range.selectNode(el);
    //     selection.removeAllRanges();
    //     selection.addRange(range);
    //     return window.getSelection().toString();
    // });

    return innerText
}

async function savePandoc(page, { original_url, version }) {
    console.log(`[📒] Converting DOM HTML to markdown with Pandoc...`.padEnd(82), prettyPath(PANDOC_PATH(page)))

    let dom_paths = [DOM_PATH(page), SINGLEFILE_PATH(page)].filter(fs.existsSync)
    if (!dom_paths) return null
    const dom_path = dom_paths[0]

    var stdout: string = ''
    var stderr: string = ''
    let result: any = null
    const BIN_NAME = 'pandoc'
    // pandoc --from html --to markdown_github --citeproc --wrap=none --highlight-style=kate
    const args = [
        BIN_NAME,
        '--from=html',
        '--to=markdown_github',
        '--wrap=none',
        '--citeproc',
        '--highlight-style=kate',
        `--output='${PANDOC_PATH(page)}'`,
        dom_path,
    ]
    try {
        ;({ stdout, stderr } = await exec(args.join(' ')));
        stdout = stdout.toString().trim()
        if (!stdout) throw 'Got empty result!'
        result = {
            TYPE: 'pandoc',
            VERSION: version,
            URL: original_url,
            cmd: args,
            markdown_file: PANDOC_PATH(page),
        }
    } catch (parse_err) {
        console.warn('[❌] Failed to run Pandoc HTML to MD conversion', parse_err, stderr)
    }
    if (!stdout) {return null}
    await overwriteFile(
        PANDOC_PATH(page),
        stdout,
    )

    // pandoc --from markdown_github --to html --citeproc --wrap=none --highlight-style=kate
    const reverse_conversion_args = [
        BIN_NAME,
        '--from=markdown_github',
        '--to=html',
        '--wrap=none',
        '--citeproc',
        '--highlight-style=kate',
        `--output='${PANDOC_PATH(page).replace('.md', '.html')}'`,
        PANDOC_PATH(page),
    ]
    try {
        ; ({ stdout, stderr } = await exec(reverse_conversion_args.join(' ')));
        stdout = stdout.toString().trim()
        if (!stdout) throw 'Got empty result!'
        result = {
            ...result,
            html_file: PANDOC_PATH(page).replace('.md', '.html'),
        }
    } catch (parse_err) {
        console.warn('[❌] Failed to run Pandoc MD to HTML conversion', parse_err, stderr)
    }
    if (!result) { return null }
    await overwriteFile(
        PANDOC_PATH(page).replace('.md', '.html'),
        result,
    )

    return result
}

async function saveReadability(page, {original_url, version}) {
    const url = await page.url()
    let html = ''
    let article = null
    try {
        html = await page.content()
        if (html.length > 14_000_000) {
            console.warn('[⚠️] Truncating readability article text because html is too long...', html.length)
            html = html.substring(0, 13_900_000)
        }
        const virtualConsole = new VirtualConsole()
        const dom = new JSDOM(html, {url, virtualConsole})
        const reader = new Readability(dom.window.document);
        article = reader.parse()
    } catch(err) {
        console.warn(`[❌] Failed to get readability article text`)
        return null
    }
    if (article) {
        console.log(`[📜] Saving readability article text (${article.textContent?.length})...`.padEnd(82), prettyPath(READABILITY_PATH(page)))
        const {content, textContent, ...metadata} = article
        if (content.trim()) {
            await overwriteFile(READABILITY_PATH(page).replace('.json', '.html'), content);
        }
        if (textContent.trim()) {
            await overwriteFile(READABILITY_PATH(page).replace('.json', '.txt'), textContent);
        }
        const readability_info = {
            TYPE: 'readability',
            VERSION: version,
            URL: original_url,
            ...metadata,
        }
        await overwriteFile(READABILITY_PATH(page), readability_info)
        return readability_info
    }
    return null
}

async function saveAccessibility(page, {original_url, version}) {
    // get accessibility tree
    const accessibility_tree = await page.accessibility.snapshot({interestingOnly: true});
    // console.log(accessibility_tree);

    // get iframe tree
    const iframes = []
    function dumpFrameTree(frame, indent='>') {
        iframes.push(indent + frame.url());
        for (const child of frame.childFrames()) {
            dumpFrameTree(child, indent + '>');
        }
    }
    dumpFrameTree(page.mainFrame(), '');
    // console.log(iframes)

    // generate simple table-of-contents of all the key html elements (e.g. h1, h2, h3, article, main, etc.)
    const outline = await page.evaluate(() => {
        const headings = []
        for (const elem of [...document.querySelectorAll("h1, h2, h3, h4, h5, h6, a, header, footer, article, main, aside, nav, section, figure, summary, table, form, iframe")] as HTMLElement[]) {
            
            // skip a tags that aren't named anchors
            if (elem.tagName.toLowerCase() == 'a' && !(elem as HTMLAnchorElement).name) continue

            // e.g. article #main-article
            const elem_id = ((typeof elem.id === 'string' && elem.id) || (elem as HTMLAnchorElement).name || elem.ariaLabel || elem.role || '')
            const elem_classes = elem.className.trim().split(' ').slice(0, 3).join(' .') || ''
            const elem_action = (elem as any).action?.split('/')?.slice(-1)?.join('/')
            const summary = elem.innerText.length > 128
                ? `${elem.innerText?.slice(0, 128)}...`
                : elem.innerText

            let prefix = ''
            let title = (elem_id ? `#${elem_id}` : '')
            if (!title && elem_classes) title = `.${elem_classes}`
            if (elem_action) title = `${title} /${elem_action}`
            if (summary) title = `${title}: ${summary}`

            // if elem is a header, prepend a #### prefix based on its level
            const level = Number(elem.tagName.toLowerCase().replace('h', ''))
            if (!isNaN(level)) {
                prefix = '#'.repeat(level)
                title = elem.innerText || elem_id || elem_classes
            } else {
                // set prefix to element's breadcrumb path
                let node = elem
                const parents = [elem.tagName?.toLowerCase().trim()]
                while (node) {
                    // add each parent element's name to the path
                    // const elem_type = node.tagName?.toLowerCase().trim() || ''
                    // if (elem_type && !['div', 'span', 'p', 'body', 'html'].includes(elem_type)) {
                    //     parents.unshift(elem_type);
                    // }
                    parents.unshift('')  // add emptystring to abbreviate path as >>>> istead of main>article>header>div>...
                    node = node.parentNode as HTMLElement
                }
                prefix = parents.join('>')
            }
            // strip all repeated whitespace and newlines
            title = title.replaceAll('\n', ' ').replace(/\s+/g, ' ').trim()

            if (prefix) {
                headings.push(`${prefix} ${title}`)
            }
        }
        // console.log(headings.join('\n'))
        return headings
    })

    console.log(`[🩼] Saving accessibility outline (${Object.keys(accessibility_tree).length})...`.padEnd(82), prettyPath(ACCESIBILITY_PATH(page)))
    // console.log(outline.filter(line => line.startsWith('#')).join('\n'))

    const accessibility_info = {
        TYPE: 'accessibility',
        VERSION: version,
        URL: original_url,
        iframes,
        headings: outline,
        tree: accessibility_tree,
    }

    await overwriteFile(
        ACCESIBILITY_PATH(page),
        accessibility_info,
    )

    return accessibility_info
}

async function saveSEO(page, {original_url, version}) {
    // collect all <meta name="title" property="og:title" content="Page Title for SEO | Somesite.com"> tags into dict
    const seo_vars = await page.evaluate(() => 
        [...document.querySelectorAll('meta')]
            .map(tag => ({key: tag.getAttribute('name') || tag.getAttribute('property') || '', value: tag.getAttribute('content') || ''}))
            .filter(obj => obj.key && obj.value)
            .sort((a, b) => a.value.length - b.value.length)
            .reduce((acc, node) => {acc[node.key] = node.value; return acc}, {})
    )

    const seo_info = {
        TYPE: 'seo',
        VERSION: version,
        URL: original_url,
        ...seo_vars,
    }

    const num_vars = Object.keys(seo_vars).length
    if (num_vars) {
        console.log(`[🔎] Saving page SEO metadata (${num_vars})...`.padEnd(82), prettyPath(SEO_PATH(page)))
        await overwriteFile(SEO_PATH(page), seo_info)
    }

    return seo_info
}

async function saveOutlinks(page, {original_url, version}) {
    // TODO: slow to iterate over all elements so many times, perhaps we can collapse everything down into one loop


    // Regular expression that matches syntax for a link (https://stackoverflow.com/a/3809435/117030):
    const LINK_REGEX = /https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*)/gi;

    const filterW3Urls = (urls) =>
        urls.filter(url =>
            url && !url.startsWith('http://www.w3.org/'))

    const filterDataUrls = (urls) =>
        urls.filter(url =>
            url && !url.startsWith('data:'))

    const html = await page.content();

    const raw = html?.match(LINK_REGEX) || [];

    const hrefs = await page.$$eval(
        "pierce/a[href]",
        elems => elems
            .map(elem => elem.href)
            .filter(url => url),
    );

    const links = await page.$$eval(
        "pierce/link[href]",
        elems => elems
            .map(({rel, href}) => ({rel, href}))
            .filter(({rel, href}) => rel !== 'stylesheet')
            .reduce((collection, entry) => {
                const {rel, href} = entry
                const non_empty_rel = collection[href]?.rel || rel
                collection[href] = {rel: non_empty_rel, href}
                return collection
            }, {})
    );

    const iframes = await page.$$eval(
        "pierce/iframe[src]",
        elems => elems.map(iframe => iframe.src).filter(url => url)
    );

    const images = await page.$$eval(
        "pierce/img[src]",
        elems => elems.map(img => img.src).filter(url => url && !url.startsWith('data:'))
    );


    const css_images = await page.$$eval(
        "pierce/*",
        elems => elems
            .map(elem => {
                const css_url_ptn = /url\(\s*?['"]?\s*?(\S+?)\s*?["']?\s*?\)/i;
                const bg_img = window.getComputedStyle(elem, null).getPropertyValue('background-image')
                const bg_url = css_url_ptn.exec(bg_img)
                return bg_url ? bg_url[1] : null
            })
    )

    const css_stylesheets = await page.$$eval(
        "pierce/link[rel=stylesheet]",
        elems => elems.map(elem => elem.href).filter(url => url)
    );

    const js_scripts = await page.$$eval(
        "pierce/script[src]",
        elems => elems.map(elem => elem.src).filter(url => url)
    );

    const outlinks_info = {
        TYPE: 'outlinks',
        VERSION: version,
        URL: original_url,
        raw: [...new Set(filterDataUrls(filterW3Urls(raw)))],
        hrefs: [...new Set(filterDataUrls(hrefs))],
        links: [...Object.values(links)],
        iframes: [...new Set(iframes)],
        images: [...new Set(filterDataUrls(images))],
        css_images: [...new Set(filterDataUrls(css_images))],
        css_stylesheets: [...new Set(filterDataUrls(css_stylesheets))],
        js_scripts: [...new Set(filterDataUrls(js_scripts))],
    }

    if (raw?.length || hrefs?.length || links?.length || iframes?.length) {
        console.log(`[🖇️] Saving page outgoing links (${raw?.length || hrefs?.length})...`.padEnd(82+1), prettyPath(OUTLINKS_PATH(page)))

        await overwriteFile(OUTLINKS_PATH(page), outlinks_info)
    }
    return outlinks_info
}


async function saveAuthStorage(page, {client, version, original_url}) {
    const url = original_url || await page.url()
    if (URL_SCHEMES_IGNORED.includes(url.split(':')[0])) return null
    if (!SAVE_AUTH_STORAGE) return null

    // const cookies = JSON.stringify(await page.cookies());  // doesnt include httponly cookies
    const auth_from_browser = {
        cookies: (await client.send('Network.getAllCookies')).cookies,
        localStorage: {},
        sessionStorage: {},
    }

    // attempt to load localStorage and sessionStorage from browser (may fail in some cases https://github.com/puppeteer/puppeteer/issues/921)
    try {
        auth_from_browser.localStorage = (await page.evaluate(() =>
            JSON.parse(JSON.stringify({[window.location.origin]: window.localStorage}))))
    } catch(err) {
        throw `Failed to get page window.localStorage! ${err}`
    }
    try {
        auth_from_browser.sessionStorage = (await page.evaluate(() =>
            JSON.parse(JSON.stringify({[window.location.origin]: window.sessionStorage}))))
    } catch(err) {
        throw `Failed to get page window.sessionStorage! ${err}`
    }

    // WARNING: small TOCTTOU gap between this read-before-write and the write below
    // can possibly overwrite changes made by other processes in this gap
    const auth_on_disk = await loadAuthStorage(page, {client}, {apply: false})

    const cookies = dedupeCookies([...auth_on_disk.cookies, ...auth_from_browser.cookies])

    const auth_info = {
        TYPE: 'auth',
        VERSION: version,
        URL: original_url,
        cookies: cookies,
        sessionStorage: merge(auth_on_disk.sessionStorage, auth_from_browser.sessionStorage),
        localStorage: merge(auth_on_disk.localStorage, auth_from_browser.localStorage),
    }
    // console.log(`[⛙] Merged ${auth_on_disk.cookies.length} existing + ${auth_from_browser.cookies.length} new -> ${auth_info.cookies.length} cookies`)
  
    console.log(`[🍪] Saving cookies/localStorage/sessionStorage (${auth_info.cookies.length})...`.padEnd(82), prettyPath(AUTH_JSON_PATH));
    await overwriteFile(AUTH_JSON_PATH, auth_info);
  
    // Write to cookies.txt file using tough-cookie + @root/file-cookie-store
    await saveCookiesTxt(cookies)

    return auth_info
}

async function saveCookiesTxt(cookies) {
    const cookies_store = new FileCookieStore(COOKIES_TXT_PATH, {auto_sync: false, lockfile: false})
    const cookie_jar = new ToughCookie.CookieJar(cookies_store)
    cookie_jar.setCookieAsync = util.promisify(cookie_jar.setCookie)
    cookies_store.saveAsync = util.promisify(cookies_store.save)
    for (const cookie of cookies) {
        const cookie_for_tough = {
            domain: cookie.domain,
            path: cookie.path,
            key: cookie.name,
            value: cookie.value,
            expires: (new Date(cookie.expires * 1000)).toISOString(),
            hostOnly: cookie.domain.startsWith('.'),
            secure: cookie.secure,
        }
        // console.log('COOKIE_FOR_TOUGH_TXT', cookie_for_tough)
        const parsed_cookie = ToughCookie.Cookie.fromJSON(cookie_for_tough)
        // console.log('COOKIE_FOR_TOUGH_TXT_TO_DUMP', parsed_cookie)
        try {
            // assemble a fake URL just to satisfy ToughCookieJar's requirement of having a URL at set time
            let url = cookie.secure ? 'https://' : 'http://'
            if (cookie.domain.startsWith('.')) {
                url = url + cookie.domain.slice(1)
            } else {
                url = url + cookie.domain
            }
            if (cookie.sourcePort && ![80, 443].includes(cookie.sourcePort)) {
                url = `${url}:${cookie.sourcePort}`
            }
            url = `${url}${cookie.path || ''}`
            await cookie_jar.setCookieAsync(parsed_cookie, url, {ignoreError: true})
        } catch(err) {
            console.error('[❌] Failed to dump browser cookie for cookies.txt...', cookie_for_tough, '->', parsed_cookie, err)
        }
    }
    console.log(`[🍪] Saving cookies TXT (${cookies.length})...`.padEnd(82), prettyPath(COOKIES_TXT_PATH));
    await cookies_store.saveAsync()
}

async function saveMetrics(page, {original_url, version, start_time, start_ts, traffic_log, redirects}) {
    const end_time = (new Date()).toISOString()
    const end_ts = Date.now()
    const metrics_info = {
        TYPE: 'metrics',
        VERSION: version,
        URL: original_url,
        ...(await page.metrics()),
        start_time,
        start_ts,
        end_time,
        end_ts,
        duration: (end_ts - start_ts),
        num_requests: traffic_log.length,
        num_redirects: Object.keys(redirects).length -1,
    }

    console.log(`[🏎️] Saving final summary + timing metrics...`.padEnd(82+1), prettyPath(METRICS_PATH(page)))
    await overwriteFile(METRICS_PATH(page), metrics_info)

    return metrics_info
}


/******************************************************************************/
/******************************************************************************/

/**************************** Utility Helpers *********************************/


function hashCode(str) {
    // get a simple integer hash for a given string (based on java String#hashCode)
    // useful only for throwaway nonces / easy deterministic random identifiers, not a replacement for sha256
    let hash = 0;
    for (let i=0; i<str.length; i++) {
       hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    return Math.abs(hash)
}

function unique(iter, key: string | ((any, number) => string)='id') {
    // uniqueify an array of objects by a value within them, key can be name of attr or getter function
    // > iter = [{id: 1}, {id: 2}, {id: 1}]
    // > Object.entries(iter) = [
    //   [ '0',  { id: 1 } ],
    //   [ '1',  { id: 2 } ],
    //   [ '2',  { id: 1 } ] ]
    // > unique(iter, 'id') => {1: {id: 1}, 2: {id: 2}}

    // > iter = {a1: {id: 1}, b2: {id: 2}, a3: {id: 1}}
    // > Object.entries(iter) = [
    //   [ 'a1', { id: 1 } ],
    //   [ 'b2', { id: 2 } ],
    //   [ 'a3', { id: 1 } ]
    // ]
    // > unique(iter, 'id') => {1: {id: 1}, 2: {id: 2}}

    const key_type = (typeof key)
    if (!['function', 'string'].includes(key_type))
        throw 'key must be either a string lookup key or a function (obj, idx) => return unique_id'

    const key_func = (key_type === 'string')
        ? (entry_obj, idx) => entry_obj[(key as string)]
        : (entry_obj, idx) => (key as Function)(entry_obj, idx)   // otherwise key is a callback func

    const seen = {}
    for (const [idx, entry_obj] of Object.entries(iter)) {
        const unique_id = key_func(entry_obj, idx)
        if (seen[unique_id] === undefined) {
            seen[unique_id] = entry_obj
        }
    }

    return seen
}

const wait = (ms: number) => new Promise(res => {
    if (ms > 10_000) {
        console.debug(`[⏲️] Waiting ${Math.round(ms/1000)}s...`)
    }
    setTimeout(res, ms)
})

const TimeoutError = Symbol()
const withTimeout = (promise, ms) => {
    // run a promise with a time limit, raises a TimeoutError if it fails
    let timer
    return Promise.race([
        promise,
        new Promise((_r, reject) =>
            timer = setTimeout(reject, ms, TimeoutError)
        ),
    ]).finally(() => clearTimeout(timer))
}

const MAX_VALID_DATE = new Date('2150-01-01T00:00:00.000Z')
const MIN_VALID_DATE = new Date('2010-01-01T00:00:00.000Z')
const UNIX_EPOCH_DATE = new Date(0)

const validateDate = (date, {min=MIN_VALID_DATE, max=MAX_VALID_DATE, singleton=UNIX_EPOCH_DATE}={}) => {
    assert((date instanceof Date), `Got invalid type for Date: ${typeof date} ${date} (expected Date)`)
    assert(String(date) !== 'Invalid Date', `Got invalid value for Date: ${typeof date} ${date}`)
    if (Number(date) === Number(singleton)) return date  // epoch singleton is always valid
    assert(date < max, `Got Date that was higher than MAX_VALID_DATE=${max}`)
    assert(date > min, `Got Date that was lower than MIN_VALID_DATE=${min}`)
    return date
}

const parseVersionDateStr = (yyyymmddtime) => {
    // YYYYMMDDhhmmssxxx or YYYYMMDDhhmmss or YYYYMMDDhhmm or YYYYMMDD -> Date
    const is_only_numbers = /^\d+$/.test(yyyymmddtime.replace('.', ''))
    assert(is_only_numbers, `Non-numeric characters in YYYYMMDD date are not allowed: ${yyyymmddtime} (while trying YYYYMMDDhhmmssxxx format)`)

    const num_digits = String(yyyymmddtime).split('.')[0].length
    assert([17, 14, 12, 8].includes(num_digits), `Got invalid number of digits (${num_digits}) in YYYYMMDD date: ${yyyymmddtime} (while trying YYYYMMDDhhmmssxxx format)`)

    const [_all, yyyy, mm, dd, hr, min, sec, ms] = /^(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?(\d{3})?$/.exec(yyyymmddtime)
    assert(yyyy && mm && dd, `Could not find YYYYMMDD`)
    const time_error_msg = `Detected YYYYMMDD[hhmm[ss[xxxx]]] but time segment is invalid ${hr}:${min || '__'}:${ms || '___'}`
    if (ms) assert(hr && min && sec, time_error_msg)
    if (sec) assert(hr && min, time_error_msg)
    if (min) assert(hr, time_error_msg)
    if (hr) assert (min, time_error_msg)

    const iso_str = `${yyyy}-${mm}-${dd}T${hr || '00'}:${min || '00'}:${sec || '00'}.${ms || '00'}Z`
    const parsed_date = new Date(iso_str)

    return validateDate(parsed_date)                        // 1970-01-01T00:00:00.000Z (ISO format)
}

const parseTimestampDateStr = (timestamp) => {
    // 1709724291000 or 1709724291000.000 or 1709724291 or 1709724291.000 -> Date
    timestamp = String(timestamp)
    const is_only_numbers = /^\d+$/.test(timestamp.replace('.', ''))
    assert(is_only_numbers, `Got invalid characters in timstamp: ${timestamp} (while trying xxxxxxxxxxxxx format)`)

    const num_digits = String(timestamp).split('.')[0].length
    assert([13, 10, 1].includes(num_digits), `Got invalid number of digits (${num_digits}) in timestamp: ${timestamp} (while trying xxxxxxxxxxxxx format)`)

    let parsed_date = null

    if (num_digits === 13) {
        parsed_date = new Date(Number(timestamp))                   // 1709724291000   (unix timestamp w/ milliseconds)
    } else if (num_digits === 10) {
        parsed_date = new Date(Number(timestamp) * 1000)            // 1709724291      (unix timestamp w/ seconds)
    } else if (num_digits === 1) {
        assert(String(timestamp) === '0', `Got invalid single-digit timestamp: ${timestamp} (while trying xxxxxxxxxxxxx format or 0 for UNIX epoch)`)
        parsed_date = UNIX_EPOCH_DATE
    }
    return validateDate(parsed_date)
}

const parseISODateStr = (iso_str) => {
    // 1970-01-01T00:00:00.000Z -> Date
    const num_digits = String(iso_str).length
    assert([24, 19, 16, 10].includes(num_digits), `Got invalid number of digits (${num_digits}) in ISO date: ${iso_str} (while trying 1970-01-01T00:00:00.000Z format)`)

    const parsed_date = new Date(iso_str)
    return validateDate(parsed_date)
}

const parseDate = (date) => {
    // date === undefined      => use today/now
    // date === null           => use unix epoch 0 aka 1970-01-01T00:00:00.000Z
    // date *= YYYYMMDDHHMMSS  => use a version date string (e.g. 20010131235958)
    // date *= 1234567...      => use a timestmap (e.g. 1709724291000)
    // date *= 1970-01-01T...  => use iso datetime (e.g. 1970-01-01T00:00:00.000Z)
    // returns -> Date

    if (date === undefined) {
        return (new Date())             // today      (2024-05-29T22:02:34.682Z) aka timestamp=1717020154682
    }
    if (date === null || date == 0) {
        return UNIX_EPOCH_DATE          // unix epoch (1970-01-01T00:00:00.000Z) aka timestamp=0
    }
    if (date instanceof Date) {
        return validateDate(date)       // JS date    Date('1970-01-01T00:00:00.000Z')
    }

    if ((typeof date) === 'number') {
        date = String(date)             // unix timestamp e.g. 1717020154682
    }
    assert((typeof date) === 'string', `Tried to parse date but got unsupported type ${(typeof date)}: ${date}`)

    const errors = [`Failed to parse Date from string: ${date}`]
    try {
        return parseVersionDateStr(date)
    } catch(err) { errors.push(err) }
    try {
        return parseTimestampDateStr(date)
    } catch(err) { errors.push(err) }
    try {
        return parseISODateStr(date)
    } catch(err) { errors.push(err) }
    
    throw errors.join('\n')
}

const versionStrFromDate = (date, {withDate=true, withTime=true, withSeconds=true, withMilliseconds=false}={}) => {
    // takes Date, returns YYYYMMDDHHMMSSXXX or YYYYMMDDHHMMSS or YYYYMMDDHHMM or YYYYMMDD
    const parsed_date = parseDate(date)

    const [date_iso, time_iso] = parsed_date.toISOString().split('T')                       // ['2001-01-31', '23:59:58.090Z']

    const components_to_use = []
    if (withDate) {                                                                        
        components_to_use.push(date_iso.replaceAll('-', ''))                                // '20010131'
    }
    if (withTime) {
        const [hr, min, sec, ms] = time_iso.replace('Z', '').replace('.', ':').split(':')   // ['23', '59', '58', '090']
        components_to_use.push(hr)
        components_to_use.push(min)
        if (withSeconds) {
            components_to_use.push(sec)
            if (withMilliseconds) {
                components_to_use.push(ms)
            }
        }
    }
    assert(components_to_use.length, 'At least one of {withDate, withTime} must be set.')

    const final_str = components_to_use.join('')                                            // 20010131235958

    assert(parseVersionDateStr(final_str))  // sanity check to make sure it parses correctly

    return final_str
}

// test date functions:
// console.log(parseDate('20120131'))
// console.log(versionStrFromDate(parseDate('20120131')))
// console.log(versionStrFromDate(parseDate('0')))
// console.log(versionStrFromDate(parseDate(0)))
// console.log(versionStrFromDate(parseDate(null)))
// console.log(versionStrFromDate())
// console.log(versionStrFromDate(parseDate('20120131235859090')))
// console.log(versionStrFromDate(parseDate('1970-01-01T00:00:00.000Z')))
// console.log(versionStrFromDate(parseDate('2024-12-01T00:00')))
// console.log(versionStrFromDate(parseDate('2024-12-01'), {withTime: false}))

const prettyPath = (path) => {
    // return a pretty-printable path where the abspath of the data dir is replaced with /data for brevity/privacy
    return path.replace(DATA_DIR, './data')
}

const pathIsHidden = (relpath) => {
    // check if a path or any of the directories above it are hidden  (e.g. ./some/.dir/abc or ./.DS_Store)
    
    // make sure test path behaves like an abspath (avoids edge-cases messing up relpaths on '' or '.' or './')
    let test_path = relpath
    if (test_path.startsWith('./'))
        test_path = test_path.substring(2)
    if (!test_path.startsWith('/'))
        test_path = path.join('/', test_path)

    // iterate through parents, checking if any parent is hidden until we reach /
    while (test_path !== '/') {
        const basename = path.basename(test_path)
        if (basename.startsWith('.')) {
            // console.log('PATH IS HIDDEN', relpath)
            return true
        }
        // otherwise set test_path to parent dir and repeat
        test_path = path.dirname(test_path)
    }
    return false
}

const pathDepth = (child_path, relative_to='.') => {
    // get the number of directory hops deep a child path is relative to '.' (or a given parent)
    
    if (child_path.startsWith('/') && !relative_to.startsWith('/')) {
        // if child_path is absolute, then relative_to must be absolute as well otherwise depth will be depth all the way to the / root
        relative_to = fs.realpathSync(relative_to)
    }
    if (relative_to.startsWith('/') && !child_path.startsWith('/')) {
        // same deal, either both paths have to be relative, or both have to be absolute
        child_path = fs.realpathSync(child_path)
    }
    const relative_path_to_root = path.relative(relative_to, child_path)
    const num_hops_down = relative_path_to_root.split('/').length
    return num_hops_down
}

interface DirentWithExtras extends fs.Dirent {
    relpath: string,
    abspath: string,
    reldepth: number,
}

async function getDirEntries(dir_path, {pwd=null, recursive=true, includeHidden=false, includeFiles=true, includeDirs=true, includeLinks=false, filter=null, maxdepth=-1}={}) {
    // get the list of all sub-paths under a given path recursively

    // console.log('GETTING DIRECTORY ENTRIES', {dir_path, pwd, recursive, includeHidden, includeFiles, includeDirs, maxdepth})

    pwd = pwd || dir_path
    let dir_abspath = dir_path

    if (!dir_abspath.startsWith(pwd)) {
        dir_abspath = path.join(pwd, dir_abspath)
    }

    assert(fs.existsSync(dir_abspath), `Tried to get directory listing for dir that doesn't exist! ${prettyPath(dir_abspath)}`)

    return (await fs.promises.readdir(dir_abspath, { recursive, withFileTypes: true }))
        .map((dirent: DirentWithExtras) => {
            // filter combined with map because relpath is re-used in both operations
            const relpath = path.join(path.relative(pwd, dirent.parentPath), dirent.name)
            // console.log('CALCULATED RELATIVE PATH', relpath)
            const abspath = path.join(dir_abspath, relpath)
            const basename = path.basename(dirent.name)
            if (!includeLinks && dirent.isSymbolicLink()) return null
            if (!includeFiles && dirent.isFile()) return null
            if (!includeDirs && dirent.isDirectory()) return null
            if (!includeHidden && pathIsHidden(relpath)) return null

            dirent.relpath = relpath
            dirent.abspath = abspath
            dirent.reldepth = pathDepth(relpath)
            // console.log('RELATIVE DEPTH MEASURED', prettyPath(dir_abspath), prettyPath(relpath), dirent.reldepth)

            if (maxdepth >= 0) {
                if ((dirent.reldepth-1) > maxdepth) return null
            }
            
            if ((typeof filter) === 'function') {
                const should_keep = filter({abspath, relpath, basename, dirent})
                if (!should_keep) {
                    // console.log('FILTER EXCLUDED RESULT', {abspath, relpath, basename, dirent})
                    return null
                }
            }

            return relpath
        })
        .filter(Boolean)
        .sort() as string[]
}


async function getTotalSize(dir_or_file_path, {pwd=null, _cache=null, filter=null, subfiles=null}={}) {
    // get the total size in bytes of a file or directory (recursively adds up file sizes within directory)

    // check _cache first
    if (_cache && (dir_or_file_path in _cache))
        return _cache[dir_or_file_path]

    // make sure dir_or_file_path is under pwd
    pwd = pwd || path.dirname(dir_or_file_path)
    let abspath = dir_or_file_path
    if (!dir_or_file_path.startsWith(pwd)) {
        abspath = path.join(pwd, dir_or_file_path)
    }

    // if it's a file, stat it and return the size
    // console.log('CALCUALTED ABSPATH', {abspath, dir_or_file_path, pwd})
    const dirent = await fs.promises.stat(abspath)
    if (dirent.isFile()) {
        // console.log('CALCULATING FILE SIZE subfile=', prettyPath(abspath))
        return dirent.size
    }

    // if it's not a file and not a directory, give up, dont try to size special files like FIFO/socket/etc.
    if (!dirent.isDirectory()) return 0

    // if it's a directory, size is the sum of all the sizes of files within
    // console.log('CALCULATING SUBDIR SIZE subdir=', prettyPath(abspath))
    let total_bytes = 0
    const files_within = subfiles || await getDirEntries(dir_or_file_path, {
        pwd,
        recursive: true,
        includeDirs: false,
        includeFiles: true,
        filter,
    })
    for (const subpath of files_within) {
        total_bytes += await getTotalSize(subpath, {pwd, _cache, filter})
    }
    return total_bytes
}


async function getDirSizes(dir_path, {pwd=null, subfiles=null, withRoot=true, filter=null, maxdepth=-1}={}) {
    // get the size of a directory and all the files within (recursively) as a number of bytes
    //  dir_path:     path   absolute or relative path of the directory you want size info for
    //       pwd:     path   (optional) absolute path of the directory you want to interpret dir_path relative to
    //  subfiles: dirent[]   (optional) instead of reading disk, you can manually provide a getDirEntries results list to use
    //  withRoot:     bool   include a summary entry for the root dir_path dir in the list as '.'
    //    filter: function   (optional) provide a filter func for dir entries ({abspath, relpath, basename, dirent}) => true/false
    //  maxdepth:   number   (optional) does not affect actual calculations, but hides entries below a certain depth in the returned output for brevity

    assert((await fs.promises.stat(dir_path)).isDirectory(), `Tried to calculate directory sizes but path is not a directory! ${dir_path}`)
    pwd = pwd || dir_path

    // {'.': 246, 'example.json': 123, 'example2.txt': 123}
    const sizes = {}

    // first collect the list of all sub-files recursively and calculate their sizes individually
    const files_within = subfiles || await getDirEntries(dir_path, {
        pwd,
        recursive: true,
        includeDirs: false,
        includeFiles: true,
        // dont pass maxdepth here, we need the entire file listing to accurately calculate parent dir sizes
        // it never makes sense to ignore subfiles beyond a certain depth for size calculation
        filter,  // filter is allowed though, useful to calculcate size of some subset of files that match a pattern
    })
    for (const subpath of files_within) {
        sizes[subpath] = await getTotalSize(subpath, {pwd, _cache: sizes, filter})
    }
    
    // then calculate the top-level directory total as the sum of all the file sizes under it
    const total_size = Object.values(sizes).reduce((a: number, b: number) => a + b, 0)

    // then calculate the subtotals of all the sub-directories
    const subdirs_within = await getDirEntries(dir_path, {pwd, recursive: true, includeDirs: true, includeFiles: false, filter, maxdepth})
    for (const subpath of subdirs_within) {
        sizes[subpath] = await getTotalSize(subpath, {pwd, _cache: sizes, filter})   // uses _cache to avoid re-computing
    }

    // if maxdepth is passed, filter results to only include paths shallower than max depth
    if (maxdepth >= 0) {
        for (const subpath of Object.keys(sizes)) {
            if (pathDepth(subpath) > maxdepth) {
                delete sizes[subpath]
            }
        }
    }

    // set total_size last so it appears at the bottom of the object in logs for convenience
    if (withRoot) {
        sizes['.'] = total_size
    }

    return sizes
}


async function getLargestPath(path_a, path_b) {
    // compare two files/directories and return the largest one of the two (calculating size recursively)
    
    path_a = await fs.promises.realpath(path_a)
    path_b = await fs.promises.realpath(path_b)
    const size_a = await getTotalSize(path_a)
    const size_b = await getTotalSize(path_b)

    // console.log('COMPARING', prettyPath(path_a), size_a, '  ', prettyPath(path_b), size_b)

    if (size_a > size_b) return path_a
    return path_b
}

async function findCommonAncestor(target_abspath, symlink_abspath, {relative=true, search_limit=DATA_DIR}: {relative?: boolean | string, search_limit?: string}={}) {
    // given a target path and a symlink path, find the common ancestor path they both share
    // (searches recursively through absolute path parent directories until a common dir is found, up to search_limit)

    search_limit = await fs.promises.realpath(search_limit)

    let relative_dir = search_limit
    if ((typeof relative) === 'boolean') {
        // if start dir is default, set it to symlinks directory path
        if (relative) {
            relative_dir = path.dirname(symlink_abspath)
        } else {
            relative_dir = search_limit
        }
    } else if ((typeof relative) === 'string') {
        // if start dir is a string, get its absolute path
        relative_dir = relative as string
    } else {
        throw `Got invalid type for relative path during common ancestor search: ${relative}`
    }

    if ((await fs.promises.stat(relative_dir)).isFile()) {
        // if start dir is a file, set it to its parent dir path
        relative_dir = path.dirname(relative_dir)
    }
    assert(
        (await fs.promises.stat(relative_dir)).isDirectory(),
        `Tried to find common ancestor starting from invalid search directory:\n    🔗 ${prettyPath(symlink_abspath)}\n    -> ${prettyPath(target_abspath)}\n    Error: search dir does not exist or is not a directory: ❌ ${prettyPath(relative_dir)}`,
    )

    const symlink_filename = path.basename(symlink_abspath)
    const target_filename = path.basename(target_abspath)
    const symlink_parent_abspath = await fs.promises.realpath(path.dirname(symlink_abspath))
    const target_parent_abspath = await fs.promises.realpath(path.dirname(target_abspath))
    const search_dir_abspath = await fs.promises.realpath(relative_dir)

    let closest_common_ancestor = search_dir_abspath

    const isAncestorCommon = (ancestor) => (
        target_parent_abspath.startsWith(ancestor)
        && symlink_parent_abspath.startsWith(ancestor))

    // check if both src and target start with the same ancestor path
    while (closest_common_ancestor !== search_limit) {
        if (isAncestorCommon(closest_common_ancestor)) break
        else {
            // otherwise go up one directory and try again
            // console.log('    ...going up a directory', prettyPath(closest_common_ancestor)+'/..')
            closest_common_ancestor = path.dirname(closest_common_ancestor)
        }
    }

    assert(
        isAncestorCommon(closest_common_ancestor),
        `Tried to create relative symlink but could not find common ancestor:\n    🔗 ${prettyPath(symlink_abspath)}\n    -> ${prettyPath(target_abspath)}\n    Error: target path and symlink path are not both under:\n      ❌ ${prettyPath(closest_common_ancestor)}`,
    )
    
    const symlink_to_ancestor_relpath = path.relative(symlink_parent_abspath, closest_common_ancestor)                             // ../../..
    const target_from_ancestor_relpath = path.join(path.relative(closest_common_ancestor, target_parent_abspath), target_filename)   // 'archive/19999999.23423523'
    const symlink_to_target_relpath = path.join(symlink_to_ancestor_relpath, target_from_ancestor_relpath)                           // '../../../archive/19999999.23423523'

    return {
        closest_common_ancestor,
        search_dir_abspath,

        target_abspath,
        target_filename,
        target_from_ancestor_relpath,
        
        symlink_abspath,
        symlink_filename,
        symlink_to_ancestor_relpath,
        symlink_to_target_relpath,
    }
}

interface StatsWithExtras extends fs.Stats {
    abspath: string
    relpath?: string
    reldepth?: number
}

async function blockUntilExists(file_path, {timeout=7_500, min_bytes=0}={}) {
    // wait up to timeout seconds until file we expect to exist appears on the filesystem
    // (used to handle eventual consistency in network filesystems where we need a delay after writing before reads show up)
    const interval = 250
    const max_tries = timeout / interval
    let tries = 0
    
    let abspath = null
    while (tries < max_tries) {
        try {
            const abspath = await fs.promises.realpath(file_path)
            assert(fs.existsSync(abspath))
            
            const dirent = await fs.promises.stat(abspath) as StatsWithExtras
            dirent.abspath = abspath
            
            if (min_bytes && (dirent.size < min_bytes)) {
                assert(dirent.size >= 1)
                // this is a valid warning but unfortunately its too common to bother showing:
                // console.warn(`[⚠️] Expected file to be >=${Math.round(min_bytes/1000)}kb but was only ${dirent.size/1000}kb:`, prettyPath(file_path))
            }
            
            return dirent
        } catch(err) {
            const waited = (tries * interval)
            if (waited === 5_000) {
                console.warn(`[⚠️] Waited >${waited/1000}s for file to appear (is filesystem or bg task running slow?):`, prettyPath(file_path))
            }
            await wait(interval)
            tries++
        }
    }
    throw `Expected file does not exist after ${timeout/1000}s: ${prettyPath(file_path)}`
}

async function overwriteSymlink(target_path, symlink_path, {relative=true, mkdirs=false, search_limit=DATA_DIR, timeout=5_000}: {relative?: boolean | string, mkdirs?: boolean, search_limit?: string, timeout?: number}={}) {
    // create a symlink from symlink_path -> target_path
    // relative: true => symlink is created as a relative link by default (it will auto-find the closest common ancestor dir, often DATA_DIR)
    // mkdirs: true   => optionally creates symlink parent dirs automatically)

    // make sure target file actually exists first
    let target_dirent
    try {
        target_dirent = await blockUntilExists(target_path, {timeout})
    } catch(err) {
        throw `Tried to create symlink pointing to file that does not exist:\n    🔗 ${prettyPath(symlink_path)}\n    -> ❌ ${prettyPath(target_path)}\n    ${err}`
    }
    const target_abspath = target_dirent.abspath
    const target_filename = path.basename(target_abspath)
    const target_parent_abspath = path.dirname(target_abspath)
    
    // make sure target is a valid file or directory and not a special character/block device/other weird file
    const target_is_dir = target_dirent.isDirectory()
    const target_is_file = target_dirent.isFile()
    assert(target_is_dir || target_is_file, `Tried to create symlink to an unsupported file type:\n    🔗 ${prettyPath(symlink_path)}\n    -> ❌ ${prettyPath(target_path)} (expected file or directory)`)

    // create symlink file parent directories if needed
    const symlink_filename = path.basename(symlink_path)
    const symlink_parent_dir = path.dirname(symlink_path)
    if (mkdirs) {
        await fs.promises.mkdir(symlink_parent_dir, {recursive: true})
    }
    try {
        assert((await fs.promises.stat(symlink_parent_dir)).isDirectory())
    } catch(err) {
        throw `Tried to create symlink in a directory that doesn't exist:\n    🔗 ${symlink_parent_dir}❌/${symlink_filename}\n    -> ${target_path}\n    ${err}`
    }
    const symlink_parent_abspath = await fs.promises.realpath(symlink_parent_dir)
    const symlink_abspath = path.join(symlink_parent_abspath, symlink_filename)

    // determine nearest common ancestor between symlink dir and target dir
    const {
        closest_common_ancestor,
        symlink_to_ancestor_relpath,
        target_from_ancestor_relpath,
        symlink_to_target_relpath,
    } = await findCommonAncestor(target_abspath, symlink_abspath, {relative, search_limit}) 
    
    // set final target path to abspath or relative path depending on {relative} options
    let target_path_final
    if (relative) {
        // make symlink into relative link (based on closest common ancestor dir between symlink_abspath and target_abspath)
        target_path_final = symlink_to_target_relpath
        // console.log('  🔗', prettyPath(symlink_abspath), '->', prettyPath(target_abspath), `(as relative link: ${target_path_final})`)
    } else {
        // make symlink into an absolute path (verbatim passed target_path)
        target_path_final = target_path
        // console.log('  🔗', prettyPath(symlink_abspath), '->', prettyPath(target_abspath), '(as absolute path)')
    }

    // remove any existing symlink at destination if there is already one there
    const random_nonce = crypto.randomBytes(16).toString('hex').substring(0, 8)
    const symlink_temp_path = `${symlink_abspath}.${random_nonce}.dup`
    try { await fs.promises.unlink(symlink_abspath) } catch(err) {}
    try { await fs.promises.unlink(symlink_temp_path) } catch(err) {}

    // create the symlink and check that it works after creation
    let created_symlink = null
    try {
        created_symlink = symlink_temp_path
        await fs.promises.symlink(target_path_final, symlink_temp_path)
        created_symlink = symlink_abspath
        await fs.promises.rename(symlink_temp_path, symlink_abspath)
    } catch(err) {
        if (String(err).includes('EISDIR')) {
            // console.warn('[⚠️] Tried to create symlink on top of existing directory', prettyPath(symlink_abspath))

            // no real recourse in this situation, and its too noisy to log every time this happens
            // it's also not always safe to move the dir out of the way, so better to just fail silently here, leaving:
            // ${symlink_abspath}.${random_nonce}.dup
        } else {
            console.warn('[⚠️] Failed to create symlink', prettyPath(created_symlink), err)
        }
    }

    let dirent
    try {
        dirent = await blockUntilExists(created_symlink, {timeout, min_bytes: 0})
        // best we can do here is just check that it exists ^, trying to check that it has the exact expected abspath that we set is bad, because its a race condition:
        // assert(dirent.abspath == target_abspath) // its often already overwritten by later activity, so final abspath may already be different
    } catch(err) {
        throw `Symlink created but does not seem to resolve to intended file:\n    🔗 ${symlink_path}\n    -> ❌ ${target_path}\n      actual=${dirent?.abspath}\n    expected=${target_abspath}\n    ${err}`
    }

    return {
        symlink_path,
        symlink_abspath: created_symlink,
        symlink_filename: path.basename(created_symlink),
        symlink_parent_abspath,
        symlink_to_ancestor_relpath,
        symlink_to_target_relpath,
        
        target_path,
        target_abspath,
        target_filename,
        target_parent_abspath,
        target_from_ancestor_relpath,
        target_path_final,
        target_is_dir,
        target_is_file,
        target_is_relative: Boolean(relative),
        
        closest_common_ancestor,
    }
}

// test symlink and common ancestor finding
// console.log(await findCommonAncestor('/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/archive/1709724410.19269/seo.json', '/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/archive/1709724410.19269/seo2.json'))
// console.log(await findCommonAncestor('/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/archive/1709724410.19269', '/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/index/snapshots_by_domain/twitter.com/1709724410.19269', {relative: true, search_limit: '/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/'}))
// console.log(await overwriteSymlink('/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/archive/1709724410.19269', '/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/index/snapshots_by_domain/twitter.com/1709724410.19269'))
// console.log(await overwriteSymlink('/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/index/snapshots_by_domain/twitter.com/1709724410.19269', '/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/index/favorite_snapshots/1709724410.19269', {relative: false, mkdirs: true, search_limit: '/Volumes/NVME/Users/squash/Local/Code/archiveboxes/archivebox-spreadsheet-bot/data/'}))



async function overwriteDir(path) {
    // delete any existing folder at the destination path (important otherwise we may create a folder inside an existing folder/symlink)
    try {
        await fs.promises.rm(path, { recursive: true, force: true });
    } catch(err) {}

    await fs.promises.mkdir(path, {recursive: true})

    return path
}

async function overwriteFile(path, contents, options={encoding: 'utf8', flag: 'w', flush: false, block: true}) {
    // write any JS value to a fresh file (e.g. String, Buffer, WritableStream, etc. anything JSON-serializable)

    const block_until_created = options.block || true
    delete options.block

    try {
        // delete any existing symlink/file present at the destination path
        // (important otherwise we may write into an existing symlink by accident)
        await fs.promises.unlink(path)
    } catch(err) {}

    try {
        let nonce = 1
        while ((await fs.promises.stat(path)).isDirectory()) {
            // if we try to write a file to a path that already has a directory in that location
            // (common when trying to write response JSON e.g. http://www.instagram.com/api/graphql returns json and www.instagram.com/api/graphql/abc returns json)
            path = path.replace(`.${nonce-1}`, '') + `.${nonce}`
            nonce++;
            if (nonce > 20) throw `Too many conflicting files while trying to write to ${prettyPath(path)}`
        }
    } catch(err) {
        if (!String(err).includes('no such file or directory')) {
            console.warn('[⚠️] Warning: Problem with conflicting directory at while trying to write file', err)
        }
    }

    // refuse writing undefined/null/function because its likely an error and not intended
    const content_is_null =  (contents === null) || (contents === undefined)
    const content_is_func = (typeof contents === 'function')
    if (content_is_null || content_is_func) {
        throw `Cannot write ${typeof contents} ${contents} to file: ${path}`
    }

    // Numbers, BigInts, and Booleans can be cast to strings, then wrt
    const content_is_primitive = ['number', 'bigint', 'boolean'].includes(typeof contents)
    if (content_is_primitive) {
        contents = String(contents)
        await fs.promises.writeFile(path, contents, options as any)
        if (block_until_created) await blockUntilExists(path, {min_bytes: Buffer.byteLength(contents)})
        return path
    }

    // Strings and Buffers can be written directly to file
    const content_is_string = (typeof contents === 'string' || contents instanceof String)
    const content_is_buffer = Buffer.isBuffer(contents)
    if (content_is_string || content_is_buffer) {
        await fs.promises.writeFile(path, contents, options as any)
        if (block_until_created) await blockUntilExists(path, {min_bytes: Buffer.byteLength(contents)})
        return path
    }
    
    // WritableStream objects can be piped into file
    const content_is_stream = (contents?.pipe)
    if (content_is_stream) {
        const stream_byte_length = contents.writableLength
        const dest_file = fs.createWriteStream(path);
        await finished(contents.pipe(dest_file))
        if (block_until_created) await blockUntilExists(path, {min_bytes: stream_byte_length})
        return path
    }

    // Objects and Arrays can be JSON-stringified then written into file
    const content_is_obj = (Array.isArray(contents) || typeof contents === 'object')
    if (content_is_obj) {
        contents = JSON.stringify(contents, null, 4)
        await fs.promises.writeFile(path, contents, options as any)
        if (block_until_created) await blockUntilExists(path, {min_bytes: Buffer.byteLength(contents)})
        return path
    }
    throw `Cannot write contents of type ${typeof contents} to file: ${path} < ${contents}`
}


async function saveExecResult(bin, args=null, {original_url, version}, {cwd='.', timeout=60_000, ...spawn_options}={}) {
    assert(bin)
    assert(original_url && original_url.includes('://'))
    assert(version)

    const BIN_NAME = bin                 // 'yt-dlp'
    const ARGS = args || []              // ['--some-arg', '--some-other-arg']
    const CWD = cwd || process.cwd()     // '.'
    const TIMEOUT = 300_000              // 5min timeout
    const PATH = process.env.PATH

    await fs.promises.mkdir(cwd, {recursive: true})

    // quick-n-dirty dump of cmd to bash script, but this might be better: https://github.com/nodejs/node/issues/34840#issuecomment-677402567
    const cmd_log_str = `#!/usr/bin/env bash
TYPE="${BIN_NAME}"
URL="${original_url}"
VERSION="${version}"

TIMEOUT=${TIMEOUT}
CWD="${CWD}"
PATH="${PATH}:$PATH"

${BIN_NAME} ${ARGS.map(arg => JSON.stringify(arg)).join(' ')}
`
    const cmd_log = path.join(cwd, 'cmd.sh')
    await overwriteFile(cmd_log, cmd_log_str)

    const stdout_log = fs.createWriteStream(path.join(cwd, 'stdout.log'))
    const stderr_log = fs.createWriteStream(path.join(cwd, 'stderr.log'))
 
    const start_date = new Date()
    const start_ts = Number(start_date)
    const start_time = start_date.toISOString()

    const child = child_process.spawn(
        BIN_NAME,
        ARGS,
        {
            cwd: CWD,
            timeout: TIMEOUT,                           // 5min timeout
            stdio: [null, 'pipe', 'pipe'],              // </dev/null >./stdout.log 2>./stderr.log
            // detached: true,                          // run in background, don't block on response
            ...(spawn_options || {}),
        },
    )
    child.stdout.setEncoding('utf8')
    child.stdout.pipe(stdout_log)
    child.stderr.setEncoding('utf8')
    child.stderr.pipe(stderr_log)

    const exec_info = {
        TYPE: BIN_NAME,
        URL: original_url,
        VERSION: version,
        bin_name: BIN_NAME,
        args: ARGS,
        timeout: TIMEOUT,
        hostname: os.hostname(),
        bin_paths: PATH,
        ppid: process.pid,
        pid: child.pid,
        start_ts,
        start_time,
        end_time: null,
        end_ts: null,
        duration: null,
        returncode: null,
        log_files: {},
        output_files: {},
    }

    // promise that resolves when the command is finished executing
    // TODO: refactor to use withTimeout
    const getResult = (timeout=TIMEOUT) =>
        new Promise((resolve, reject) => {
            const loop = setInterval(() => {
                if (exec_info.end_time) {
                    clearInterval(loop)
                    clearTimeout(timer)
                    resolve(exec_info)
                }
            }, 100)

            const timer = setTimeout(() => {
                clearInterval(loop)
                if (!exec_info.end_time) {
                    reject(new Error(`Process ${BIN_NAME} did not finish within TIMEOUT=${TIMEOUT}`))
                }
            }, timeout);
        })

    const logFilesFilter = ({relpath}) =>
        ['cmd.sh', 'stdout.log', 'stderr.log'].includes(relpath)

    const outputFilesFilter = ({relpath}) =>
        !['cmd.sh', 'stdout.log', 'stderr.log', 'index.json'].includes(relpath)

    const getOutputFiles = async (filter=outputFilesFilter) => {
        return await getDirInfo(CWD, {filter, withHelpers: false, withRoot: false, maxdepth: 6})
    }

    child.on('close', async (returncode) => {
        const end_date = new Date()
        exec_info.returncode = returncode
        exec_info.pid = child.pid
        exec_info.end_ts = Number(end_date)
        exec_info.end_time = end_date.toISOString()
        exec_info.duration = exec_info.end_ts - exec_info.start_ts
        exec_info.log_files = await getOutputFiles(logFilesFilter)
        exec_info.output_files = await getOutputFiles(outputFilesFilter)

        const end_metadata = ` 
# END_TIME="${exec_info.end_time}"
# DURATION=${exec_info.duration}
# RETURNCODE=${exec_info.returncode }
`
        await fs.promises.appendFile(cmd_log, end_metadata)

        // write exec_info json (which includes file list) to CWD/index.json
        await overwriteFile(path.join(CWD, 'index.json'), exec_info)
    })
    // child.unref()  // dont wait for child process to close
    
    const start_metadata = `
#################### LAST RUN LOG ####################
# HOSTNAME="${exec_info.hostname}"
# PPID=${exec_info.ppid}
# PID=${exec_info.pid}
# START_TIME="${exec_info.start_time}"
`
    await fs.promises.appendFile(cmd_log, start_metadata)

    return {
        ...exec_info,
        getResult,
    }
}

const HASH_CACHE = {}

async function sha256File(file_path: string, {pwd=null}: {pwd?: string}={}) {
    return new Promise((resolve, reject) => {
        pwd = pwd || path.dirname(file_path);
        if (!file_path.startsWith(pwd)) {
            file_path = path.join(pwd, file_path);
        }

        const dirent = fs.statSync(file_path);
        const abspath = fs.realpathSync(file_path);
        const cache_key = `${abspath}:${dirent.size}:${dirent.mtimeMs}`; // PATH:SIZE:LAST_MODIFIED_TIME
        if (cache_key in HASH_CACHE) {
            resolve(HASH_CACHE[cache_key]);
        }

        const hash = crypto.createHash('sha256');
        const rs = fs.createReadStream(abspath);
        rs.on('error', reject);
        rs.on('data', chunk => hash.update(chunk));
        rs.on('end', () => {
            const final_hash = hash.digest('hex');
            HASH_CACHE[cache_key] = final_hash;
            resolve(final_hash);
        });
    }) as Promise<string>
}

async function getDirSha256(dir_path, {pwd=null, withRoot=true, filter=null, maxdepth=-1, subfiles=null}={}) {
    // console.log('CALCULATING SHA256 OF FILES IN DIR', dir_path, {withRoot, filter, maxdepth})
    //  dir_path:     path   absolute or relative path of the directory you want the merkle sha256 for
    //       pwd:     path   (optional) absolute path of the directory you want to interpret dir_path relative to
    //  withRoot:     bool   include a summary entry for the root dir_path dir in the list as '.'
    //    filter: function   (optional) provide a filter func for dir entries ({abspath, relpath, basename, dirent}) => true/false
    //  maxdepth:   number   (optional) does not affect actual calculations, but hides entries below a certain depth in the returned output for brevity
    //  subfiles: dirent[]   (optional) instead of reading disk, you can manually provide a getDirEntries results list to use

    pwd = pwd || dir_path
    if (!dir_path.startsWith(pwd)) {
        dir_path = path.join(pwd, dir_path)
    }

    const dirent = await fs.promises.stat(dir_path)
    assert(dirent.isDirectory(), `Tried to compute sha256 of path but missing or not a directory! ${dir_path}`)
    assert((maxdepth >= -1), `maxdepth must be -1, 0, or 1, 2, 3, etc... (got ${maxdepth})`)
    
    // assert(!(filter && withRoot), `Cannot generate root hash (consistently) when a custom filter is provided!`)

    // get the sha256 of every file in a directory recursively (excluding hidden files and symlinks)
    // EQUIVALENT TO: find . -type f -not -path '*/.*' -print0 | sort -z | xargs -0 sha256sum
    const all_subfiles = (subfiles as string[]) || await getDirEntries(dir_path, {
        pwd,
        recursive: true,
        includeFiles: true,
        includeDirs: false,

        // ~~maxdepth,~~    // dont pass maxdepth here, we need the entire file listing to accurately calculate parent dir hashes.
                            // it never makes sense to ignore subfiles beyond a certain depth for hash calculation. Hashes are
                            // only useful IDs if they are consistent+repeatable, hashing to an arbitrary depth will produce 
                            // many different hashes for the same directory, which is not something we need/want polluting the hash space.

        
        filter,  // we do however allow passing a manual filter funcs which does actually affect the hash
                 // this is useful to allow quick checks to see whether a certain subset of files has changed or not
    })
    const hashes: {[key: string]: string} = {}
    let hashable_summary_str = ''
    for (const subfile of all_subfiles) {
        // {'versions/20240413144307/screen recording.mp4': '1df4d9c3aca8b36f1f73e327d56038f80a35db407a298edb16c72576d7dd894e', ...}
        hashes[subfile] = await sha256File(subfile, {pwd})
        const relpath = path.relative(await fs.promises.realpath(dir_path), await fs.promises.realpath(path.join(pwd, subfile)))
        hashable_summary_str += `${hashes[subfile]}  ./${relpath}\n`
    }
    // console.log('CALCULATED HASHES FOR ALL SUBFILES IN DIR', dir_path, Object.keys(hashes).length)

    // get list of subdirectories and recursively hash every subdirectory
    // EQUIVALENT TO: find . -type d -not -path '*/.*' -maxdepth ${maxdepth} -print | sort
    const subdirs = await getDirEntries(dir_path, {pwd, recursive: true, includeHidden: false, includeDirs: true, includeFiles: false, filter, maxdepth})

    // for each subdirectory, get its hash recursively and store it in the hash list
    for (const subdir of subdirs) {
        // console.log('GETTING SUBDIR HASH', subdir)
        // a directory's hash is defined as the hash of all the *files* within (excluding dirs/symlinks/hidden)
        const subdir_hashes = await getDirSha256(
            subdir,
            {pwd, withRoot: true, filter, maxdepth: 0},
        )
        hashes[subdir] = subdir_hashes['.']
    }
    // console.log('CALCULATED HASHES FOR ALL SUBDIRS IN DIR', dir_path, subdirs.length)

    // filter results if maxdepth is provided
    if (maxdepth >= 0) {
        for (const subpath of Object.keys(hashes)) {
            if (pathDepth(subpath) > maxdepth) {
                delete hashes[subpath]
            }
        }
    }
    // console.log('LIMITED OUTPUT DUE TO MAXDEPTH', maxdepth, Object.keys(hashes).length)

    // calculate the hash of the root '.' folder by hashing all of hashes of its contents
    // EQUIVALENT TO: find . -type f -not -path '*/.*' -print0 | sort -z | xargs -0 sha256sum | sha256sum
    if (withRoot) {
        // pass the first command's output containing the file list + hashes into another sha256
        // to get the final hash of the whole directory combined
        // console.log('CALCULATING FINAL ROOT HASH for ', dir_path)
        // console.log(hashable_summary_str)
        hashes['.'] = crypto.createHash('sha256').update(hashable_summary_str).digest('hex') as string
        // console.log('--->', hashes['.'])
    }

    return hashes
}


async function getDirInfo(dir_path, {pwd=null, withRoot=true, withHelpers=true, filter=null, maxdepth=-1, subfiles=null}={}) {
    // get a detailed JSON/dumpable index of a directory's contents, w/ merkle sha256's, sizes, and mimeTypes
    //    dir_path:     path   absolute or relative path of the directory you want size info for
    //         pwd:     path   (optional) absolute path of the directory you want to interpret dir_path relative to
    //    withRoot:     bool   include a summary entry for the root dir_path dir in the list as '.'
    // withHelpers:     bool   attach many extra helper attrs/funcs to results (beyond JSON-serializable core data)
    //      filter: function   (optional) provide a filter func for dir entries ({abspath, relpath, basename, dirent}) => true/false
    //    maxdepth:   number   (optional) does not affect actual calculations, but hides entries below a certain depth in the returned output for brevity
    //    subfiles: dirent[]   (optional) instead of reading disk, you can manually provide a getDirEntries results list to use

    // {
    //   ...
    //   'example.txt': { ... },
    //   'foobar/example.mp3': { ... },
    //   '.': {                                 // this is the fully agumented result when withHelpers=true
    //     is_file: false,
    //     is_dir: true,
    //     filename: '.',
    //     basename: '1709039915.378868',
    //     mimeType: 'inode/directory'
    //     extension: undefined,
    //     num_bytes: 11540961,
    //     num_subpaths: 15,
    //     sha256: '9fc58b3ed887e7139338062ebd49bd6795373759e8acb73d2f7a40f1413789da',
    //     reldepth: 1,
    //     relpath: './',
    //     cwd: '/opt/archivebox/data/archive/1709039915.378868/',
    //     dirname: '/opt/archivebox/data/archive',
    //     abspath: '/opt/archivebox/data/archive/1709039915.378868',
    //     dirent: Stats {
    //       dev: 16777240,
    //       mode: 16895,
    //       uid: 501,
    //       ...
    //       mtimeMs: 1717160622956.1357,
    //       ctimeMs: 1717160622956.1357,
    //     },
    //     created: '2024-05-31T13:03:42.956Z',
    //     modified: '2024-05-31T13:03:42.956Z',
    //     summary: './data/archive/1709039915.378868 (inode/directory 11541kb 9fc58b3e)',
    //     helptext: 'Verify these hashes by running:\n' +
    //       '  cd /opt/archivebox/data/archive/1709039915.378868 \n' +
    //       "  find . -type f -not -path '*/.*' -print0 | sort -z | xargs -0 sha256sum | sha256sum",
    //   },
    // }

    pwd = pwd || dir_path
    if (!dir_path.startsWith(pwd)) {
        dir_path = path.join(pwd, dir_path)
    }

    // calculate hashes and sizes recursively
    const hashes = await getDirSha256(dir_path, {pwd, withRoot, filter, maxdepth, subfiles})
    const sizes = await getDirSizes(dir_path, {pwd, withRoot, filter, maxdepth, subfiles})

    const num_total_subpaths = Object.keys(hashes).filter(name => name !== '.').length

    const details = {}
    for (const [filename, sha256] of Object.entries(hashes)) {
        if (filename === '.' && !withRoot) continue

        const abspath = await fs.promises.realpath(path.join(dir_path, filename))
        const dirent = await fs.promises.stat(abspath)
        const num_subpaths = Object.keys(hashes).filter(subpath => subpath.startsWith(filename + '/')).length
        const is_file = dirent.isFile()
        const is_dir = dirent.isDirectory()

        // bare-bones info suitable for JSON dumps/exports
        const basic_info = {
            sha256,
            num_bytes: sizes[filename],
            created: (new Date(dirent.ctimeMs)).toISOString(),
            mimeType: undefined,
            extension: undefined,
            num_subpaths: undefined,
        }
        if (is_dir) {
            basic_info.mimeType = 'inode/directory'
            basic_info.extension = undefined
            basic_info.num_subpaths = (filename === '.') ? num_total_subpaths : num_subpaths
        }
        if (is_file) {
            basic_info.mimeType = mime.lookup(abspath) || null
            basic_info.extension = path.extname(filename)
            basic_info.num_subpaths = undefined
        }

        // extra helpers suitable for usage in other areas of the codebase
        const info_with_helpers = {
            ...basic_info,
            filename,
            basename: path.basename(abspath),
            dirname: path.dirname(abspath),
            cwd: dir_path,
            relpath: is_dir ? (filename + '/') : filename,
            reldepth: pathDepth(filename),
            abspath,
            is_file,
            is_dir,
            dirent,
            modified: (new Date(dirent.mtimeMs)).toISOString(),
            summary: `${prettyPath(abspath)} (${basic_info.mimeType} ${Math.round(basic_info.num_bytes/1000)}kb ${sha256.substring(0, 8)})`,
            helptext: undefined,
        }
        if (filename === '.') {
            info_with_helpers.helptext = `Verify these hashes by running:\n  cd ${prettyPath(abspath)} \n  find . -type f -not -path '*/.*' -print0 | sort -z | xargs -0 sha256sum | sha256sum`
        }

        if ((typeof filter) === 'function') {
            if (!filter(info_with_helpers)) continue
        }

        details[filename] = withHelpers ? info_with_helpers : basic_info
    }
    return details
}

// console.log(await getDirSha256(
//     '/opt/archivebox/data/archive/1709039915.378868/',
//     {
//         withRoot: true,
//         maxdepth: -1,
//         filter: ({relpath}) => relpath.startsWith('versions'),
//     },
// ))
// console.log(await getDirSizes(
//     '/opt/archivebox/data/archive/1709039915.378868/',
//     {
//         withRoot: false,
//         maxdepth: 2,
//         filter: ({relpath}) => !relpath.startsWith('versions'),
//     },
// ))
// console.log(await getDirInfo(
//     '/opt/archivebox/data/archive/1709039915.378868/',
//     {
//         withRoot: true,
//         withHelpers: true,
//         maxdepth: 1,
//         // filter: ({relpath}) => relpath.startsWith('versions'),
//     },
// ))

type DetectFilenameOptions = {
    url?: string,
    response?: HTTPResponse | Response,
    page?: Page,
    dir?: string,
    abspath?: string,
    filename?: string,
    basename?: string,
    extension?: string,
    mimeType?: string,
    resourceType?: string,
}

async function detectFilename({ url, response, page, dir, abspath, filename, basename, extension, mimeType, resourceType }: DetectFilenameOptions) {
    // this function takes a url (and/or response/page), and detects the abspath,dir,filename,basename,extention,mimeType
    // from the URL (+ any enforced path components passed in via args)
    // example: detectFilename({url: 'https://example.com/favicon.png', extension: 'ico'}) outputs 'favicon.ico'
    //
    // it has some quirks that are specific to archiving and may not behave as you expect
    // e.g. if visiting the url https://example.com/error.zip returns a 500 text/html error page
    // this may still save it as a .zip with mimeType=application/x-zip and ignore the response mimeType the url ends in .zip
    // however, if the url has no extension, e.g. https://example.com/error it will 
    // auto-detect the mimeType based on the response and append an extension, saving as error.html
    //
    // ⚠️ SECURITY WARNING: think carefully about the permissions, shell injection, and RCE implications of any changes made here ⚠️
    // this function writes untrusted web content to the filesystem using auto-detected mimetype to co-erce the extension,
    // which can be dangerous (e.g. what if one of these downloads is a malicious ransomware .exe, do we really want to give it .exe?
    // if we do, how do we make sure it never gets executed? (without damaging the integrity of the copy)

    if (!(response || page)) throw 'Either a page or a response must be provided in order to detect mimeType & URL'

    if (response && (typeof response.headers !== 'function')) {
        const node_fetch_response: Response = response as Response
        response = {
            url: () => node_fetch_response.url,
            headers: () => node_fetch_response.headers,
        } as unknown as HTTPResponse
    }
    response = response as HTTPResponse

    url = url || response?.url() || (await page.url())
    if (!url) throw 'URL was not provided and could not be detected from {response, page}'

    // Document, Stylesheet, Image, Media, Font, Script, TextTrack, XHR, Fetch, Prefetch, EventSource, WebSocket, Manifest, SignedExchange, Ping, CSPViolationReport, Preflight, Other
    try {
        resourceType = resourceType || response?.request()?.resourceType()
    } catch(err) {
        // ignore, sometimes response is null/not available
    }
    const resourceTypeToMimeType = {
        'Stylesheet': 'text/css',
        'Script': 'application/x-javascript',
        'WebSocket': 'application/json',
        'Website': 'text/html',
    }
    
    mimeType = mimeType || resourceTypeToMimeType[resourceType]   // guess extension based on request resourceType
    extension = extension || (mimeType ? mime.extension(mimeType) : null)

    // handle special url cases (e.g. schemes in URL_SCHEMES_IGNORED)
    if (url.startsWith('about:blank')) {
        filename = 'about_blank'
        mimeType = 'text/html'
    }
    else if (url.startsWith('data:')) {
        filename = `data__${hashCode(url)}`
    }

    // console.log('detectFilename>', {url, dir, abspath, filename, basename, extension, mimeType, resourceType})

    if (abspath) {
        if (dir || filename || basename || extension)
            throw '{abspath} should not be passed with other options (e.g. dir, filename, basename, extension)'
        var {dir, base: filename, ext: extension, name: basename} = path.parse(abspath)
        // path.parse('/home/user/dir/file.txt') returns:
        // { root: '/',
        //   dir: '/home/user/dir',
        //   base: 'file.txt',
        //   ext: '.txt',
        //   name: 'file' } 
    } else {
        dir = dir || path.resolve(process.cwd())

        filename = filename                                         // https://example.com/a.1.zip?e.pdf=2#g.h=3  => a.1.zip
            || (new URL(url)).pathname.split('/').at(-1)          // https://example.com/file124.rss  => file124.rss    prefers last component of path with no query/hash, falls back to domain name if no path
            || 'index'                                            // https://example.com/abc/def/     => index.html
            //|| (new URL(url)).hostname.replaceAll('.', '_')     // https://example.com              => example_com  (but if disabled, this would be index.html)
    }
    if (!filename) throw 'filename/abspath were not passed and could not be detected from url'
    
    const path_extname = path.extname(filename)
    const resp_mimetype = response && (
        (response as any).mimeType
        || response.headers()['content-type']?.split(';')[0]
        || resourceTypeToMimeType[resourceType]
        || 'application/octet-stream'
    )

    mimeType = mimeType                                         // https://example.com/a.1.zip?e.pdf=2#g.h=3  => application/x-zip    prefers mimetype based on extension in path, falls back to response mimeType
        || (path_extname && mime.lookup(path_extname))                    // https://example.com/file124.rss  => application/rss+xml
        || resp_mimetype                                                  // https://example.com/get?type=png => image/png
        
    extension = extension
        || (path_extname && path_extname.replace('.', ''))      // https://example.com/a.1.zip?e.pdf=2#g.h=3  => zip                  prefers extension in path, falls back to response mimeType's suggested extension
        || (resp_mimetype && mime.extension(resp_mimetype))               // https://example.com              => html
        || ''                                                             // https://example.com/websocket.1  => 
    if (extension.startsWith('.'))
        extension = extension.slice(1)

    basename = basename                                         // https://example.com/a.1.zip?e.pdf=2#g.h=3  => a.1                  prefers to filename in path (without extension), falls back to domain name
        || (path.parse(filename).name)                          // https://mp4dl.example.com        => mp4dl_example_com

    basename = basename.slice(0, 120)                            // truncate at 120 characters (leaving 8 chars for .ext)
    basename = basename.replace(/[^a-zA-Z0-9%+?&=@;_ \.-]/g, '') // strip characters not allowed in filenames

    filename = basename + '.' + extension

    if (filename.endsWith('.'))
        filename = filename.slice(0, -1)

    abspath = abspath || path.join(dir, filename)

    // console.log('detectFilename<', {url, dir, abspath, filename, basename, extension, mimeType, resourceType})

    return {
        url,
        dir,
        abspath,
        filename,
        basename,
        extension,
        mimeType,
        resourceType,
        resp_mimetype,
    }
}

interface DowloadOptions extends DetectFilenameOptions {
    browser?: Browser
    expected_mimetype?: string
    timeout?: number
}

async function download({ url, browser, page, response, dir, abspath, filename, basename, extension, expected_mimetype, timeout }: DowloadOptions) {
    url = url || (response as HTTPResponse)?.url() || (await page?.url())
    ALREADY_ARCHIVED.add(url.slice(0, 4096))   // prevent running whole archive task on tabs we create for just for downloading

    browser = browser || (page && (await page.browser()))
    timeout = timeout || 120_000
    expected_mimetype = expected_mimetype || ''
    let newPage = null
    let errors = []
    let num_bytes = 0
    let bytesBuffer = null


    // if we need to fetch the url (i.e. it's not already been requested)
    if (!response) {
        if (!browser) throw 'No {browser} or {page} was provided to download with'
        newPage = await browser.newPage()
        if (page) await page.bringToFront()  // if origin page is provided, make sure it stays in foreground
        response = await newPage.goto(url, {timeout: timeout, waitUntil: 'networkidle0'})
        if (page) await page.bringToFront()  // if origin page is provided, make sure it stays in foreground
    }
    url = url || (response as HTTPResponse)?.url() || (await newPage?.url()) || (await page?.url());
    const response_mimetype = (response as HTTPResponse).headers()['content-type']?.split(';')[0] || 'text/html'

    // detect the filename we should write to based on provided url/response/page/filename/extension suggestions
    var {
        dir,
        abspath,
        filename,
        basename,
        extension,
        mimeType,
    } = await detectFilename({url, page, response, dir, abspath, filename, basename, extension, mimeType})

    // if mimeType is passed, make sure response matches expected mimetype, otherwise consider download a failure
    if (!response_mimetype.startsWith(expected_mimetype)) {
        errors.push(`Expected ${expected_mimetype} but got ${response_mimetype}`)
    } else {

        // download the file using puppeteer's response.buffer()
        try {
            // write the response bytes into the output file
            bytesBuffer = await (response as HTTPResponse).buffer()
            await overwriteFile(abspath, bytesBuffer)
            num_bytes = bytesBuffer.length
        } catch(err) {
            errors.push(err)
        }

        // security check to make sure downloaded file is not executable (random binaries downloaded off the internet = dangerous)
        fs.access(abspath, fs.constants.X_OK, (err) => {
            if (!err) console.warn(
                '[⚠️] SECURITY WARNING: Downloaded file appears to be executable:', prettyPath(abspath),
                '\n     (be careful running untrusted programs downloaded from the internet!)'
            )
        })
    }

    // if we opened a dedicated page for downloading, close it now
    if (newPage) {
        newPage.close()
    }

    if (errors.length) {
        // console.warn(`[❌] Downloading ${url} (${mimeType}) to ${abspath} failed:`, JSON.stringify(errors, null, 4))
    } else {
        console.log(`[💾] Downloaded ${url.substring(0, 40)}  (${num_bytes} ${mimeType})...`.padEnd(82), prettyPath(abspath))
    }

    return {
        url, response, errors,
        dir, abspath, filename, basename, extension, mimeType,
        bytesBuffer, num_bytes,
    }
}


/************************** Puppeteer Launching *******************************/


async function startCluster(puppeteer, args=CHROME_ARGS_DEFAULT) {
    console.log(`[🎭] Launching ${CHROME_CLUSTER_WORKERS}x Chromium browsers with puppeteer-cluster:`.padEnd(82), prettyPath(CHROME_PROFILE_PATH))
    const cluster = await Cluster.launch({
        puppeteer,
        monitor: true,
        maxConcurrency: CHROME_CLUSTER_WORKERS,
        sameDomainDelay: 2550,
        workerCreationDelay: 250,
        timeout: 300_000,                       // total ms timeout for an entire task (1000ms * 60s * 5m)
        concurrency: Cluster.CONCURRENCY_PAGE,  // share cookies between all tabs in a given browser
        puppeteerOptions: {
            args,                                           // all the chrome launch CLI args
            ignoreDefaultArgs: true,                        // trust me, we have enough args already...
            // dumpio: true,                                // full debug log output, super noisy
        }
    })
    console.log('*************************************************************************')
    return cluster
}

async function remoteBrowser(puppeteer, {browserURL, browserWSEndpoint}) {
    console.log('[🎭] Connecting Puppeteer to existing Chromium browser via:', browserURL || browserWSEndpoint)
    let completed_initial_connection = false
    const browser = await puppeteer.connect({browserURL, browserWSEndpoint, defaultViewport: null, targetFilter: () => completed_initial_connection})
    completed_initial_connection = true
    console.log('*************************************************************************')
    return browser
}

async function startBrowser(puppeteer, args=CHROME_ARGS_DEFAULT) {
    console.log('[🎭] Launching Puppeteer Chromium browser...'.padEnd(82+1), prettyPath(CHROME_PROFILE_PATH))

    const browser = await puppeteer.launch({ignoreDefaultArgs: true, args, dumpio: true})
    globalThis.browser = browser
    console.log('*************************************************************************')
    
    // store all active tabs on global var by url for easier vscode interactive debugging
    const storeTabForDebugger = async (target) => {
        try {
            globalThis.tabs = globalThis.tabs || {}
            const url = target.url()
            const page = await target.page()
            if (!page || page?.isClosed()) {
                delete globalThis.tabs[url]
            } else {
                globalThis.tab = page
                globalThis.tabs[url] = page
            }
        } catch(err) {console.warn(err)}
    }
    browser.on('targetcreated', storeTabForDebugger)
    browser.on('targetchanged', storeTabForDebugger)
    browser.on('targetdestroyed', storeTabForDebugger)

    // wait for initial extension background.js/service worker targets to load
    await wait(3_000)

    // prime the extensions cache
    const extensions = await getChromeExtensionsFromCache({browser})
    globalThis.extensions = extensions  // for easier debugging only

    // give the user 2min to check any issues with the initial startup pages (bot profile pages),
    // solve captchas, re-login, etc. then close them after that to save resources
    const startup_pages = (await browser.pages())
    const startup_page_close_delay = 120_000
    setTimeout(async () => {
        for (const page of startup_pages) {
            try { await page.close() } catch(err) { /* page may already be closed by now, which is fine */ }
        }
        
    }, startup_page_close_delay)
    
    // setup any extensions that need final runtime configuration using their options pages
    // await setup2CaptchaExtension({browser, extensions})

    // open a placeholder page so browser window stays open when there are no active archiving pages
    // (it's annoying to have the entire window open/close/open/close/etc every time an archive task runs)
    const empty_page = await browser.newPage()
    await wait(250)
    await empty_page.goto('chrome://version')
    await wait(500)
    console.log('*************************************************************************')

    return browser
}

async function startAPIServer(port=API_SERVER_PORT, host=API_SERVER_HOST, taskCallback=null) {
    // taskCallback should be an async function that takes ({url}) => and does something with it
    assert(taskCallback && (typeof taskCallback === 'function'))

    const server = createServer(async (req, res) => {
        if (req.method === 'POST') {
            console.log(`[API][POST] ${req.url}`)
            let body = '';

            req.on('data', (chunk) => {
                body += chunk;
            });

            req.on('end', () => {
                try {
                    const jsonData = JSON.parse(body);
                    // Process the JSON data
                    console.log(jsonData);
    
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ message: 'JSON data received' }));
                } catch (error) {
                    res.writeHead(400, { 'Content-Type': 'application/json' });
                    res.end(JSON.stringify({ error: 'Invalid JSON data' }));
                }
            });
        } else if (req.method === 'GET') {
            console.log(`[API][GET] ${req.url}`)
            const parsedUrl = new URL(`http://${host}:${port}${req.url}`)
            const query = new URLSearchParams(parsedUrl.search);
            const url = query.get('url');
            if (url && url.includes('://')) {
                res.writeHead(200, { 'Content-Type': 'text/plain' });
                try {
                    await taskCallback({url})
                    res.end(`${url}\n${TASK_PATH(url)}`);
                } catch(err) {
                    res.end(`${url}\n${TASK_PATH(url)}\n${err}`);
                }
            } else {
                res.writeHead(500, { 'Content-Type': 'text/plain' });
                res.end(`Bad URL: ${url}\n\nExpected: /?url=https://example.com/url/to/archive`);
            }
        } else {
            res.writeHead(405, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Method not allowed' }));
        }
    })

    server.listen(port, host, () => {
        console.log(`[🎰] API Server listening for requests on http://${host}:${port}/?url=...`);
    })
    console.log('*************************************************************************')

    return server
}

async function main(urls, cluster=CHROME_CLUSTER) {
    process.chdir(DATA_DIR)

    const extensions =      await getChromeExtensionsFromPersona({CHROME_EXTENSIONS, CHROME_EXTENSIONS_DIR})
    const args =            getChromeArgs({...CHROME_LAUNCH_OPTIONS, CHROME_EXTENSIONS: extensions})
    const preferences =     getChromePreferences({CHROME_PREFERENCES_DEFAULT, CHROME_PREFERENCES_EXTRA, CHROME_DOWNLOADS_DIR, CHROME_EXTENSIONS: extensions})
    const Puppeteer =       applyChromePreferences(PupeteerExtra, CHROME_PREFERENCES_PATH, preferences)
    
    Puppeteer.use(StealthPlugin());
    // Puppeteer.use(ReplPlugin());
    // handled by uBlock Origin & ReCaptcha browser extensions, probably not needed here anymore:
    // Puppeteer.use(RecaptchaPlugin({
    //     provider: {id: '2captcha', token: API_KEY_2CAPTCHA},
    //     visualFeedback: true,
    // }))
    // const AdblockerPlugin = require('puppeteer-extra-plugin-adblocker')
    // puppeteer.use(AdblockerPlugin({ blockTrackers: true }))

    if (cluster) {
        // launch browser with multiple tabs w/ puppeteer
        const cluster = await startCluster(Puppeteer, args)

        const handleTask = async ({url}) => cluster.queue(url, botArchiveTask)
        const server = await startAPIServer(API_SERVER_PORT, API_SERVER_HOST, handleTask)

        console.log('[📋] Running tasks in parallel with puppeteer cluster...')
        for (const url of urls) {
            if (fs.existsSync(path.join(TASK_PATH(url), 'aiqa.json'))) {
                try {
                    JSON.parse((await fs.promises.readFile(path.join(TASK_PATH(url), 'aiqa.json'))).toString())
                    console.log('    skipping (already present):', TASK_PATH(url), url)
                    continue
                } catch(err) {
                    // pass
                }
            }
            cluster.queue(url, botArchiveTask)
            await wait(3_000)
        }

        await cluster.idle();
        await cluster.close();
    } else {
        // launch single new browser w/ puppeter / connect to remote CDP browser w/ puppeteer
        const browser = await startBrowser(Puppeteer, args)
        // const browser = await remoteBrowser(Puppeteer, {browserURL, browserWSEndpoint})

        // run speedtest in the background
        speedtest({browser})

        const handleTask = async ({url}) => await botArchiveTask({page: (await browser.newPage()), data: url})
        const server = await startAPIServer(API_SERVER_PORT, API_SERVER_HOST, handleTask)

        // wait for any pre-run setup tasks or server requests
        await wait(5_000)

        let num_succeeded = 0
        let num_failed = 0

        console.log(`[📋] Running ${urls.length} tasks sequentially with puppeteer browser...`)
        for (const url of urls) {
            const run_count = (num_succeeded + num_failed) || 1

            // check if task should be run or skipped based on existing snapshot data present in directory
            const metrics_path = path.join(TASK_PATH(url), 'metrics.json')
            const screenshot_path = path.join(TASK_PATH(url), 'screenrecording.gif')
            const aiqa_path = path.join(TASK_PATH(url), 'aiqa.json')
            const versions_path = path.join(TASK_PATH(url), 'versions')
            if (fs.existsSync(metrics_path) && fs.existsSync(screenshot_path) && fs.existsSync(aiqa_path) && fs.existsSync(versions_path)) {
                try {
                    const ai_qa_result = JSON.parse(await fs.promises.readFile(aiqa_path, 'utf-8'))
                    console.log(prettyPath(TASK_PATH(url)), `${ai_qa_result.pct_visible}%`, ai_qa_result.website_brand_name, url.substring(0, 80))
                    assert(ai_qa_result.website_brand_name)
                    continue
                } catch(err) {
                    // pass
                }
            }
            let delay = 0

            // create a new browser page and run the archiving task
            const page = (await browser.newPage())
            try {
                console.log(ANSI.black + `◤==============================================================================[${String(run_count).padStart(3)}]/[${urls.length}]◥` + ANSI.reset)
                await botArchiveTask({page, data: url})
                delay = 1_000
                num_succeeded += 1
            } catch(err) {
                console.error('[❌] Archiving task failed!', url)
                console.error(err)
                num_failed += 1
                delay = 15_000   // extra delay if there are errors
            }
            console.log(ANSI.black + `◣==============================================================================[☑ ${num_succeeded}][🆇 ${num_failed}]◢` + ANSI.reset)
            
            // check for abnormally high failure rates and exit early if needed
            const failure_pct = Math.round((num_failed/run_count) * 100)
            if (failure_pct > 50) {
                if (run_count > 5) {
                    console.warn(`[⚠️] ${failure_pct}% Task failure rate is very high! Will self-cancel after 10 URLs if >50% continue to fail...`)
                }
                if (run_count > 10) {
                    throw `Too many tasks failed in a row! Quitting early after ${run_count}/${urls.length} tasks.`
                }
            }
            
            // increase the delay between tasks based on the ratio of how many are failing:succeeding
            delay = Math.pow(4, (num_failed/(num_succeeded + 3))) * delay
            // e.g. 0:1 failure ratio ==  1  * delay ==   1 ~ 15s
            //      1:1 failure ratio ==  5  * delay ==   5 ~  1m ... 5^(failed:succeeded) exponential increase
            //      2:1 failure ratio == 25  * delay == 25s ~  6m
            //      3:1 failure ratio == 125 * delay ==  2m ~ 31m
            //      etc...
            //      up to 1hr+
            delay = Math.min(delay, 3_600_000)   // 1hr maximum delay between tasks
            delay = Math.max(delay, 1_000)       // 1s minimum delay between tasks
            if (delay > 2_500) {
                console.log('... waiting', Math.round(delay/1000), 'seconds (self rate-limit)...')
            }
            await wait(delay)   // base ratelimit
            console.log()
        }


        if (PASSIVE_ARCHIVING) {
            // replace these as-needed:
            const browserURL = 'http://localhost:9222/'
            const browserWSEndpoint = 'ws://localhost:9222/devtools/browser'

            const driver_browser = browser || await remoteBrowser(Puppeteer, {browserURL, browserWSEndpoint})
            const archiver_browser = {} //await startBrowser(Puppeteer, args)

            const extensions = await getChromeExtensionsFromCache({browser: driver_browser})

            // close both browsers if either one is closed
            let browser_is_open = true
            driver_browser.on('disconnected', async () => {browser_is_open = false})  // await archiver_browser.close()
            // archiver_browser.on('disconnected', async () => {browser_is_open = false; await driver_browser.close()})

            // handle any tab navigation to a new URL in the driver browser
            const handleUserNavigation = async (target) => {
                const url = target.url()
                const page = await target.page()
                // const client = await target.createCDPSession()

                if (target.type() == 'page' && page && url) {
                    console.log(ANSI.black + '==============================================================================' + ANSI.reset)
                    console.warn('[➕] DRIVER BROWSER NAVIGATED:', ANSI.blue, url, ANSI.reset)
                    
                    try {
                        await passiveArchiveTask({browser: driver_browser, page, url})
                        await wait(3_000)
                    } catch(err) {
                        console.error('[❌] Archiving task failed!', url)
                        console.error(err)
                        await wait(10_000)   // base ratelimit
                    }
                    console.log(ANSI.black + '==============================================================================' + ANSI.reset)
                    // await client.send('Page.enable')
                    // await client.send('Page.setWebLifecycleState', {state: 'active'})
                }
                // await client.send('Runtime.runIfWaitingForDebugger')
            }

            // setup handler to archive new page whenever one is opened
            driver_browser.on('targetcreated', handleUserNavigation)
            driver_browser.on('targetchanged', handleUserNavigation)

            console.log('------------------------------------------------------')
            console.log('[👀] Waiting for browser tabs to be opened by human...')
            while (browser_is_open) {
                await wait(2_000)
            }
        } else {
            while (true) {
                await wait(2_000)
            }
        }

        await browser.close()
    }
    console.log('[✅] Finished all tasks and stopped browsers.')
    process.exit(0);
}


/******************************************************************************/
if (import.meta.main) {
    main(URLS).catch(console.error);
}

/******************************************************************************/

// if we want to handle CLI args in the future, minimist is great:
// var argv = require('minimist')(process.argv.slice(2));
// console.log(argv); // --url=https://example.com --binpath=/browsers/chromium-1047/bin/chromium --datadir=/Chromium
// const {url, binpath, datadir} = argv;


// OLD CODE, may be useful in the future if we need audio in screenrecordings:
// async function setupScreenrecordingWithAudio(page, wss) {
//     console.log('[🎬] Setting up screen-recording plugin...');
//     const stream_port = (await wss).options.port;
//     // streamPage = await (page.browser()).newPage()
//     await page.goto(`chrome-extension://jjndjgheafjngoipoacpjgeicjeomjli/options.html#${stream_port}`)
//
//     // puppeteer-stream recording start
//     streamFile = fs.createWriteStream(SCREENRECORDING_PATH(page))
//     stream = await getStream(page, {
//       audio: true,
//       video: true,
//       bitsPerSecond: 8000000,       // 1080p video
//     });
//     stream.pipe(streamFile);
//     return {stream, streamFile}
//
//     // puppeteer-stream recording stop & cleanup
//     if (stream && streamFile) {
//         await stream?.destroy();
//         streamFile?.close();
//         // await streamPage.close();
//     }
// }

