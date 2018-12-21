# Binaries for running ArchiveBox

This folder contains all the executables that ArchiveBox provides.


# Adding it to your `$PATH`
To be able to run ArchiveBox from anywhere on your system, you can add this entire folder to your path, like so:

**Edit `~/.bash_profile`:**
```bash
export PATH=/opt/ArchiveBox/bin:$PATH
```

# Running executables directly

If you don't want to add ArchiveBox to your `$PATH` you can also call these executables directly with their full path, like so:

`/opt/ArchiveBox/bin/ArchiveBox https://example.com/some/feed.rss`
