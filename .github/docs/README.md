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
