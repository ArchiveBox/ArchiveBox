## Security

- Snapshot replay now rejects symbolic links that resolve outside the snapshot,
  including while captures are still running. This prevents disclosure of files
  readable by the ArchiveBox process through archived symlinks. Links to files
  within the snapshot continue to work.
- Replay and directory downloads also reject symlink aliases to private browser
  runtime files.

Discovered by Yves Soete of Blacksight LLC.
