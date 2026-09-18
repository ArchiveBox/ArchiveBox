# Building the 0.8.6rc1 documentation

The `docs` submodule remains pinned to the wiki revision shipped with 0.8.6rc1.
This configuration renders that historical user guide without installing
ArchiveBox, importing Django, or updating the wiki checkout.

```sh
git submodule update --init docs
uv run --no-project --with-requirements .github/docs/requirements.txt \
  sphinx-build -W --keep-going -b html -c .github/docs docs /tmp/archivebox-docs
```

`conf.py` adapts GitHub wiki links, heading levels, and obsolete local anchors
in memory. Search options without a prose section link to their exact
0.8.6rc1 source definition; the removed USE_CURL option points to CURL_BINARY. The original user documentation is not rewritten.
Generated Python autodoc scaffolding is outside this standalone user guide;
its legacy Django-dependent builder is not loaded.

Read the Docs uses `.github/.readthedocs.yaml` and the same strict HTML command.
Keep its project configuration-file setting pointed at that path.

The release label follows the immutable `v0.8.6rc1` tag; its original
`pyproject.toml` still declares `0.8.6rc0` and is left unchanged.
