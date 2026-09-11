# Personas: import browser logins and settings

A persona holds a copy of one Chromium browser profile, its cookies, and its browser settings. ArchiveBox uses that identity when you pass `--persona=personal` to `add`. Chrome, Chromium, Brave, and Edge are detected automatically. Other Chromium browsers work with an explicit profile path and browser executable.

## Import on the computer where you use the browser

Run the import as your normal desktop user, with your OS keychain unlocked. For Chrome, Chromium, Brave, Edge, Vivaldi, and Opera on desktop systems, ArchiveBox reads a consistent copy of the cookie database and decrypts it through the host OS keychain without launching the browser. On headless Linux without a desktop D-Bus session, it exports through a temporary profile copy using the originating browser instead. It does not change your original profile. Close the source browser first if you want a consistent copy of all settings and site storage.

```bash
uv tool install --python 3.13 --prerelease explicit --upgrade 'git+https://github.com/ArchiveBox/ArchiveBox.git@dev'
mkdir -p ~/archivebox/data
cd ~/archivebox/data
archivebox init
archivebox persona create --import=brave personal
archivebox add --persona=personal 'https://example.com/private-page'
```

Use `--import=chrome`, `--import=chromium`, or `--import=edge` for those browsers. Your OS may ask to allow keychain access for the import. Cookie values are never printed by the command.

If you have multiple profiles, select one explicitly:

```bash
archivebox persona create --import=chrome --profile='Profile 1' work
```

The command reports success only after profile copying and cookie export finish. If import fails, it exits nonzero, removes a newly created persona, and preserves an existing persona's imported files. Re-importing replaces the selected persona's profile and exported state with the new source state.

## Docker on macOS or Windows

**Import on the host, then archive in Docker using the same data directory.** Mounting the raw browser directory alone does not give Linux access to macOS Keychain or Windows credential protection. An encrypted cookie database is not a portable login session.

```bash
# On your host, after installing ArchiveBox with uv as above:
mkdir -p ~/archivebox/data
cd ~/archivebox/data
archivebox init
archivebox persona create --import=brave personal

# Now use the resulting collection in Docker:
docker pull archivebox/archivebox:dev
docker run --rm -v "$PWD:/data" archivebox/archivebox:dev \
    add --persona=personal 'https://example.com/private-page'
```

Both commands use the public CLI. No copying files into persona directories, manual database changes, cookie extensions, or credentials pasted into Docker are needed. Refresh expired sessions by re-running the host import command. Stop archiving while replacing an existing persona.

## Explicit source paths and other Chromium browsers

`--source` accepts either a browser user-data directory or the exact profile directory. Known browsers select their own OS cookie decoder. For other Chromium browsers, also pass `--browser-binary` to export through a temporary copy launched with the originating browser:

```bash
archivebox persona create --import=brave \
    --source="$HOME/Library/Application Support/BraveSoftware/Brave-Browser" \
    --profile=Default personal

# Example for another Chromium browser on macOS:
archivebox persona create --import=vivaldi \
    --source="$HOME/Library/Application Support/Vivaldi" \
    personal
```

In Linux containers, `--source=/browser` can select a read-only mounted browser directory, but the originating browser and its decryption credentials must also be available. Prefer importing on the desktop host to avoid keyring and browser-installation setup inside Docker.

## A running browser with CDP

For any Chromium browser already exposing an authorized Chrome DevTools Protocol endpoint:

```bash
archivebox persona create --import=http://127.0.0.1:9222 personal
```

This exports cookies and accessible open-tab storage. It cannot copy browser preferences or extensions; use the profile import above when settings are needed. Keep debugging endpoints private.

## What is preserved

The selected profile is normalized to `Default` within the persona. Preferences, bookmarks, extensions and their settings, local storage, IndexedDB, and service-worker storage are copied. Cache, temporary writes, runtime locks, and saved tab sessions are discarded so archiving does not reopen your personal tabs. Other browser profiles are not imported. `auth.json` retains exported cookie attributes such as HttpOnly and SameSite; `cookies.txt` supplies the formats that wget/curl and other non-browser extractors accept.

Browser versions and products can differ in which settings and extensions they support. Windows app-bound cookie encryption may prevent direct cookie export; use an authorized live CDP endpoint if the browser refuses to decrypt the clone. A website can expire or reject a session, so verify the saved screenshot or HTML contains the private content. A successful HTTP response or extractor exit alone does not prove authentication.
