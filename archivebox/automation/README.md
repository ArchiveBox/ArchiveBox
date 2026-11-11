# Snapshot automation

Superusers manage ordered rules at `/admin/automation/`. Rules respond to completed captures, AI completion, tag addition/removal, or
folder changes. Each rule matches nested all/any groups of domain, URL, title,
tag, changed-tag, or visibility conditions, then adds/removes
tags, moves the snapshot into a folder, or changes its visibility. Domain equality
compares the parsed hostname, so `example.com.evil.test` does not match
`example.com`. An optional stop flag prevents later rules from changing a match.

The normal daemon runner evaluates new sealed captures and durable change events
in batches. Tag/folder events wait until the capture completes. Each event is
processed once with its rule audit and changes in one transaction. Changes made
by rules do not generate further events; ordered rules within the same event
can see earlier actions without recursive loops. Capture-completion triggers leave older captures untouched until an administrator
previews and applies the rule. Tag, folder and AI triggers respond to future
changes to existing captures as well.
The preview examines the latest 500 candidates after an optional URL/title filter,
shows at most 100 matches, and signs the exact candidate IDs and current rule.
Applying an expired or edited preview does nothing. Conditions are checked again
before each write. An audit row and its changes commit in one short transaction.
Rules never delete captured files. `archivebox manage automation` evaluates
pending automatic rules manually.

The screenshot gallery uses `screenshots.prepare(admin_base_url, username,
password)` after real Hacker News captures complete. It logs into the real server,
saves a rule through its form, previews matches, and applies the signed preview.
`gallery_entries` registers the populated rule and history pages for every gallery
viewport. No synthetic captures or UI substitutions are used.

## AI enrichment

`/admin/automation/ai/` configures optional automatic summaries and tags using the
existing OpenCode provider. Enable OpenCode and connect a provider in Agent first.
Choose a `provider/model` or leave the model blank to use OpenCode's default.
Automatic processing is opt-in and starts with future completed captures. Existing
captures can be selected explicitly for enrichment.

A durable job records queue state, the actual OpenCode session, completion/error,
summary and proposed tags. Language, tag style, curated topics and custom
instructions are frozen when each job is queued. Curated topics restrict output
to exact allowed names (case-insensitive matching); formatting applies only when
no curated list is set. The settings page previews the exact instruction prefix. The worker reads bounded saved text/HTML (up to 60,000
characters) from successful archive outputs. The page content is sent as untrusted
data to a JSON-output session with all external tool permissions denied.
Validated topic tags are additive, and AI summaries are separate from human notes
and captured original files. Provider failures remain visible and require an
explicit retry; they are never presented as successful summaries. Jobs waiting
for a provider are bounded by a ten-minute deadline.

The AI gallery helper `ai_screenshots.prepare(..., model=..., data_dir=..., project_dir=...)` submits the real
Hacker News homepage and recent story captures through the UI, waits for the
actual provider results, and fails on provider errors. Its `gallery_entries`
registers the populated summary page and expanded summary on an actual saved page.
The collector enables OpenCode only in its screenshot collection and defaults
`UI_SCREENSHOT_AI_MODEL` to `openai/gpt-5.4-mini`; overrides must use `openai/`.
It requires an existing connected OpenAI provider or `OPENAI_API_KEY`, which is
sent directly to the local OpenCode authentication API and stored only in its
protected credential store. Keys are never written to screenshot evidence.
The helper runs the real automation worker from its explicit collection path; no
synthetic summaries, tags or successful job statuses are ever inserted.
