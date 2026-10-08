# Building historical documentation

The `docs` submodule remains pinned to the wiki revision shipped with each release.
This configuration renders that historical user guide without installing
ArchiveBox, importing Django, or updating the wiki checkout.

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.11.3 and Python 3.13, matching CI and Read the Docs. `uv` can install Python when needed.

```sh
git submodule update --init docs
uv run --no-project --python 3.13 --with-requirements .github/docs/requirements.txt \
  sphinx-build -W --keep-going -b html -c .github/docs docs /tmp/archivebox-docs
```

`conf.py` adapts GitHub wiki links, heading levels, and obsolete local anchors
in memory. Configuration options without a prose section link to their exact
release source definition. The original user documentation is not rewritten.
Generated Python autodoc scaffolding is outside this standalone user guide;
its legacy Django-dependent builder is not loaded.

Read the Docs uses `.github/.readthedocs.yaml` and the same strict HTML command.
Keep its project configuration-file setting pointed at that path.

`requirements.txt` pins the complete documentation dependency set. To update it,
edit `requirements.in` and run:

```sh
uv pip compile --universal --python-version 3.13 .github/docs/requirements.in \
  --output-file .github/docs/requirements.txt
```

## Live version picker

Read the Docs loads `https://docs.archivebox.io/docs-live-picker/_static/archivebox-versions.js`
through Addons > Custom script. The hidden `docs-live-picker` version keeps this
asset available independently of future main or release documentation builds. The picker
shows all published stable releases in the newest minor series, one release per older
minor series, and the `latest` and `dev` branches. For a historical series with no
stable release (0.8), it keeps the newest published release candidate. The script uses
the published version inventory and preserves existing navigation URLs.

The hosting checkout command checks out the original main/tag commit, then overlays
only the historical Sphinx build files from pinned docs repair commits. Application
source, release tags, and pinned wiki revisions remain those of the selected release.
Keep the docs repair branches available for fetching these configuration commits.

## Publication policy

The default documentation version is the current published stable tag. Automation
rule 2264 matches `^v[0-9]+\.[0-9]+\.[0-9]+$` and activates each new stable tag as
the default. Development documentation remains at `/dev/`; release candidates
are excluded from the custom picker.

The repository's legacy `stable` branch predates the 0.9 releases. Keep that RTD
version inactive. Exact redirects `/stable/*` and `/en/stable/*` point to
`/page/:splat`, so stable links follow RTD's default release and preserve page paths.

The 0.9 rendering overlay comes from the docs-only PR #1908. It escapes HTML in
API examples, preserves wiki heading aliases, and links to the documented source
revision. Only `docs/conf.py` and `docs/_templates/layout.html` are overlaid; the
selected release's application and authored Markdown remain unchanged.

The project checkout command also resolves external PR builds to GitHub's
`refs/pull/<number>/head` ref. Current pinned configuration:

```sh
git init .
git config remote.origin.url "$READTHEDOCS_GIT_CLONE_URL"
docs_ref="$READTHEDOCS_GIT_IDENTIFIER"
if [ "$READTHEDOCS_VERSION_TYPE" = "external" ]; then docs_ref="refs/pull/$READTHEDOCS_VERSION/head"; fi
git fetch --depth=1 origin "$docs_ref"
git checkout --force --detach FETCH_HEAD
repair=; extra=; case "$(git rev-parse HEAD)" in 6c06da5581637806e686e6b39f177d20569a6902|9766ea21a7eb51138237889dedba51c835e35def|b186e98cd2eeb5cb375dedfaa21abcae1abec2be) repair=c003f783caa66374adb6d05445da2e852e66117a ;; 3830544e131d2f7d8f76daf0fbf5528f846c6019) repair=8209d4844d4f14ff7b2afad3ebc873c04c187782 ;; 122bd0cc2ed9229818ae233c5e887a988efce8c2) repair=0fef07cd4d9e3e6b0ea98f81c81f79ccaae50047 ;; 0e2928e758d93767ef60b7610c2df44e4df56ca9) repair=31349e1fa786e600349bbf50fbb78908bd28df23; extra=index.md ;; aa5a674a17e414d4fdb2cb17f183ac3e24d6b42c) repair=8b7ba251c7a312c4b6f41ce5327c56c2e958d8ce; extra=index.md ;; 2b4384c3110cb378b4d9e13ae12601a3e97a5d6f) repair=2ad7a5a1ace978d76ba533e5e7bb97869dc06854; extra=index.md ;; esac; if [ -n "$repair" ]; then git fetch --depth=1 origin "$repair" && git checkout FETCH_HEAD -- .github/docs .github/.readthedocs.yaml $extra; fi
case "$READTHEDOCS_VERSION" in latest|main|dev|v0.9.*) git fetch --depth=1 origin 223c282bb61ff460cf9a2d7bb2486215c1fdaff2 && git checkout FETCH_HEAD -- docs/conf.py docs/_templates/layout.html ;; esac
```
