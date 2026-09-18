# Historical 0.1.0 documentation

This documentation-only branch starts at the immutable `v0.1.0` tag.
The original README, application files, and pinned wiki (when present) remain unchanged.
Sphinx reads them without installing or importing the historical application.
The render-time adapter fixes historical link and heading syntax only; the visible warning
explains that these old installation commands and external services may no longer work.

```sh
READTHEDOCS=True uv run --no-project --with-requirements .github/docs/requirements.txt \
  sphinx-build -E -a -W --keep-going -b html -c .github/docs . /tmp/archivebox-historical-docs
```

Read the Docs must use `.github/.readthedocs.yaml`. The pinned theme supplies
its version selector and listens for Read the Docs addon version data.
