const assert = require('node:assert/strict');
const {test} = require('node:test');
const {safeReplayUrl, replayFailureDetails} = require('../domains/replay_diagnostics.js');

test('diagnostic URLs omit credentials, queries and fragments, including embedded replay URL', () => {
  assert.equal(safeReplayUrl('https://user:password@example.com/story?token=secret#private'), 'https://example.com/story');
  assert.equal(safeReplayUrl('http://localhost/replay/w/id/mp_/https://user:password@example.com/story?token=secret#private'), 'http://localhost/replay/w/id/mp_/https://example.com/story');
  assert.equal(safeReplayUrl('data:text/html,secret'), null);
  assert.equal(safeReplayUrl('not a URL'), null);
  assert.equal(safeReplayUrl('https://example.com/' + 'a'.repeat(2000)).length, 1024);
});

test('missing replay frame remains explicit and emits no content', async () => {
  assert.deepEqual(await replayFailureDetails(null, 'https://example.com/?secret=x', 'https://example.com/', []), {
    story: 'https://example.com/', replay: 'https://example.com/', frame: null, unavailable: true, failures: [],
  });
});
