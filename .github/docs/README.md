# Building the 0.7.4 documentation

The `docs` submodule remains pinned to the wiki revision shipped with 0.7.4.
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
0.7.4 source definition. The original user documentation is not rewritten.
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
asset available independently of future main or release documentation builds. This applies the release policy and puts `dev`
after `latest` across existing versions without rebuilding them. The script uses
the published version inventory and preserves existing navigation URLs.

The hosting checkout command checks out the original main/tag commit, then overlays
only the historical Sphinx build files from pinned docs repair commits. Application
source, release tags, and pinned wiki revisions remain those of the selected release.
Keep the docs repair branches available for fetching these configuration commits.
