# Historical 0.2.4 documentation

This documentation-only branch starts at the immutable `v0.2.4` tag.
The original README, application files, and pinned wiki (when present) remain unchanged.
Sphinx reads them without installing or importing the historical application.
The render-time adapter fixes historical link and heading syntax only; the visible warning
explains that these old installation commands and external services may no longer work.

```sh
git submodule update --init docs
READTHEDOCS=True uv run --no-project --with-requirements .github/docs/requirements.txt \
  sphinx-build -E -a -W --keep-going -b html -c .github/docs . /tmp/archivebox-historical-docs
```

Read the Docs must use `.github/.readthedocs.yaml`. The pinned theme supplies
its version selector and listens for Read the Docs addon version data.
