
import {getEnvironmentConfig} from 'archivebox/util/config.js'
import {getScopeConfig} from 'archivebox/util/config.js'
import {getPuppeteerPage} from 'archivebox/util/page.js'


const env_config = await getEnvironmentConfig()
const snapshot_page = await archivebox.getPuppeteerPage(url, config)


async function extract(page) {
    const cwd = process.cwd()
    const config = await getScopeConfig(url=url)
    const page = await archivebox.getPuppeteerPage(url, config)

    const output_path = path.join(cwd, 'screenrecording.mp4')
    let recorder = null
    const {
        SCREENRECORDING_DURATION_LIMIT=60,
        SCREENRECORDING_CODEC='libx264',
        SCREENRECORDING_SAVE_GIF=true,
    } = config

    page.on('setup', async () => {

        recorder = new PuppeteerScreenRecorder(page, {
            followNewTab: false,
            recordDurationLimit: SCREENRECORDING_DURATION_LIMIT,
            // fps: 25,
            // ffmpeg_Path: '<path of ffmpeg_path>' || null,
            // videoFrame: {
            //   width: 1024,
            //   height: 768,
            // },
            // videoCrf: 18,
            videoCodec: SCREENRECORDING_CODEC,
            // videoPreset: 'ultrafast',
            // videoBitrate: 1000,
            // autopad: {
            //   color: 'black' | '#35A5FF',
            // },
            // aspectRatio: '4:3',
        });

        await recorder.start(output_path)
        await archivebox.savePageState(page, {recorder})
    })
    await once(page, 'setup')
    await once(page, 'BEHAVIORS_STARTED')
    page.on('BEHAVIORS_FINISHED', async () => {
        if (!recorder) return
        await recorder.stop()

        // convert video to GIF
        if (SCREENRECORDING_SAVE_GIF) {
            try {
                const BIN_NAME = process.env.FFMPEG_BINARY || 'ffmpeg'
                const child = child_process.spawn(
                    BIN_NAME,
                    [
                        '-hide_banner',
                        '-loglevel', 'error',
                        '-ss', '3',
                        '-t', '10',
                        '-y',
                        '-i', output_path,
                        '-vf', "fps=10,scale=1024:-1:flags=bicubic,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
                        '-loop', '0',
                        output_path.replace('.mp4', '.gif'),
                    ],
                    {
                        cwd,
                        timeout: 60_000,
                        // stdio: [null, 'pipe', 'pipe'],
                        stdio: 'ignore',
                        detached: true,                          // run in background, don't block on response
                    },
                )
                await blockUntilExists(output_path.replace('.mp4', '.gif'), {min_bytes: 100, timeout: 40_000})
                console.log(`[🎥] Saved screen-recording GIF with ffmpeg pid=${child.pid} (${duration/1000}s)...`.padEnd(82), prettyPath(output_path.replace('.mp4', '.gif')))
            } catch(err) {
                console.log('[❌] Failed to convert video to GIF:', err)
            }
        }
    })
    await once(page, 'BEHAVIORS_FINISHED')
}

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
