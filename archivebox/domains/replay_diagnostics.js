// Gallery failure metadata only: never retain page text, credentials or URL queries.
function safeReplayUrl(value) {
  const url = URL.parse(value);
  if (!url || !['http:', 'https:'].includes(url.protocol)) return null;
  // Replay paths embed the original URL, including possible userinfo.
  const embedded = url.pathname.search(/https?:\/\//);
  const pathname = embedded < 0 ? url.pathname : url.pathname.slice(0, embedded) + (safeReplayUrl(url.pathname.slice(embedded)) || '[invalid]');
  return (url.origin + pathname).slice(0, 1024);
}

async function replayFailureDetails(frame, storyUrl, replayUrl, failures) {
  let timer;
  let state = {unavailable: true};
  if (frame) {
    try {
      state = await Promise.race([
        frame.evaluate(() => ({readyState: document.readyState, textLength: document.body?.innerText.length || 0})),
        new Promise(resolve => { timer = setTimeout(() => resolve({unavailable: true}), 1000); }),
      ]);
    } catch {
      // A detached/crashed frame must not hide the original replay assertion.
    } finally {
      clearTimeout(timer);
    }
  }
  return {story: safeReplayUrl(storyUrl), replay: safeReplayUrl(replayUrl), frame: frame ? safeReplayUrl(frame.url()) : null, ...state, failures};
}

module.exports = {safeReplayUrl, replayFailureDetails};
