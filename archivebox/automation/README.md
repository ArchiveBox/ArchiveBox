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

