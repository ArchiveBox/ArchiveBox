# Setting Up Search

## How to Search in ArchiveBox

You can search your ArchiveBox data in a number of ways:

- using the CLI: `archivebox list --filter-type=search 'text to search'` (`archivebox list --help` for more)
- using the Web UI: both the `/public` index and `/admin/core/snapshot` pages provide a search box
- using the REST API: `/api/v1/list?filter_type=search` provides the same search interface as the CLI  
- by searching the archive data folder directly with external tools (e.g. macOS Spotlight, [Cerebro](https://www.cerebroapp.com/), `ag`, [Yacy](https://yacy.net/), etc.)

![image](https://github.com/ArchiveBox/ArchiveBox/assets/511499/637675ee-bf4a-49f9-b936-c2da1bd64410)

<br/>

---

## How Search Works

ArchiveBox search works by doing substring matches in `Snapshot` metadata fields (`url`, `title`, `timestamp`, `tags`), and by searching the full archived content within each Snapshot (using the selected search backend below). You can find the search implementation source code here: [`archivebox/core/views.py: PublicIndex.get_queryset()`](https://github.com/ArchiveBox/ArchiveBox/blob/dev/archivebox/core/views.py#:~:text=title__icontains).

> *Note: ArchiveBox currently only returns the bare list of snapshots that match when performing a search.*  
>   
> This will be [improved in the future](https://zulip.archivebox.io/#narrow/stream/154-support/topic/Full.20Text.20Search.20works.2E.2E.2E.20but.20is.20there.20a.20UI.3F) to highlight the *specific paragraph/line/area that matched* within a Snapshot.  
> For now we recommend using Ctl+F in the browser or one of the external tools listed above to further filter for a term within a Snapshot's contents.

<br/>

## ArchiveBox Search Backends

ArchiveBox provides a number of "Search Backend Engines" to tune its performance & behavior for different use-cases.
```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_ENGINE=ripgrep
uv run --project "$project_dir" --no-sync archivebox version
uv run --project "$project_dir" --no-sync archivebox config --get SEARCH_BACKEND_ENGINE
```

By default out-of-the-box, the selected engine is a simple but efficient tool similar to `grep -r` called [`ripgrep`](https://github.com/BurntSushi/ripgrep).

Ripgrep is [currently the fastest](https://blog.burntsushi.net/ripgrep/) available *filesystem search* tool that scans over the raw archived files on every search. We chose it as the default so that beginners and 95% of users with small collections can have an experience that "just works", without needing to install and maintain complex additional dependencies or background workers.

However, there are some fundamental limitations of scanning through every file on disk each time a search is done, so ArchiveBox provides a number of additional search backend options for when users outgrow `ripgrep`.

> [!TIP]
> **You should consider switching ArchiveBox to use `sonic` or another backend IF:**
> 
> - you have more than 1,000 Snapshots saved in your archive
> - your archive data is stored on a slower filesystem like a spinning hard drive or remote network mount
> - you want more advanced search features like stemming, boolean operators, and ability to search PDFs, eBooks, ZIP/tar files, etc.

<br/>

<a name="ripgrep"></a>

### `ripgrep` *(the default)*

If you do not already have `ripgrep` installed, follow the [instructions here](https://github.com/BurntSushi/ripgrep#installation) to get it.
ArchiveBox will use `ripgrep` by default if it is found, however you can explicitly configure it to be used like so:

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox install ripgrep
uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_ENGINE=ripgrep
uv run --project "$project_dir" --no-sync archivebox version
test -L "$ABXPKG_LIB_DIR/env/bin/rg"
uv run --project "$project_dir" --no-sync archivebox add --plugins=wget "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
search_result="$(uv run --project "$project_dir" --no-sync archivebox search --search contents:ripgrep 'ArchiveBox docs fixture')"; grep -q "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}" <<< "$search_result"
```

#### Pros
- supports advanced searching with regex patterns
- simple, few moving parts, and broadly available for all OSs and CPU architectures
- 0 idle resource use as there is no background indexer process running
- 0 additional disk storage needed as it searches the original data instead of maintaining a separate index
- reasonably fast on NVMe and SSD drives for small collections

#### Cons
- very slow as archive collection size increases (doesn't scale well beyond 500~1,000 Snapshots)
- very slow if underlying filesystem is slow (e.g. HDDs or network mounts)
- doesn't support stemming, boolean operators, or other advanced full-text search features

<br/>

<a name="ripgrep-all"></a>

### `ripgrep-all` (aka `rga`)

The same as ripgrep except that it supports searching more binary filetypes like PDFs, eBooks, Office documents, zip, tar.gz, etc.

To use it, follow the [install instruction for your OS](https://github.com/phiresky/ripgrep-all#installation), then configure ArchiveBox to use it like so:

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync abxpkg env --install --lib="$ABXPKG_LIB_DIR" --binproviders env,brew --overrides '{"brew":{"install_args":["rga"]}}' rga >/dev/null
uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_ENGINE=ripgrep
uv run --project "$project_dir" --no-sync archivebox config --set RIPGREP_BINARY="$ABXPKG_LIB_DIR/env/bin/rga"
test -L "$ABXPKG_LIB_DIR/env/bin/rga"; "$ABXPKG_LIB_DIR/env/bin/rga" --version
uv run --project "$project_dir" --no-sync archivebox add --plugins=wget "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
search_result="$(uv run --project "$project_dir" --no-sync archivebox search --search contents:ripgrep 'ArchiveBox docs fixture')"; grep -q "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}" <<< "$search_result"
```

<br/>

<a name="ugrep"></a>

### `ugrep`

Not tested by the ArchiveBox team but it's very similar to `ripgrep` and may work as a drop-in replacement, with some caveats. (contributions welcome to improve support)

`ugrep` is similar to `ripgrep` and `ripgrep-all` in that it's an indexless disk-search tool, but it provides some more of the full-text search features without the performance overhead of maintaining a separate search backend worker with an independent index.

https://github.com/Genivia/ugrep

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"; uv run --project "$project_dir" --no-sync archivebox init; uv run --project "$project_dir" --no-sync abxpkg env --install --lib="$ABXPKG_LIB_DIR" --binproviders env,apt,brew ugrep >/dev/null; test -L "$ABXPKG_LIB_DIR/env/bin/ugrep"; "$ABXPKG_LIB_DIR/env/bin/ugrep" --version; uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_ENGINE=ripgrep; uv run --project "$project_dir" --no-sync archivebox config --set RIPGREP_BINARY="$ABXPKG_LIB_DIR/env/bin/ugrep"; uv run --project "$project_dir" --no-sync archivebox add --plugins=wget "${ARCHIVEBOX_DOCS_URL_TWO:-https://example.com/}"; search_result="$(uv run --project "$project_dir" --no-sync archivebox search --search contents:ripgrep 'ArchiveBox docs fixture')"; grep -q "${ARCHIVEBOX_DOCS_URL_TWO:-https://example.com/}" <<< "$search_result"
```

#### Pros

- supports [boolean operators](https://github.com/Genivia/ugrep#bool) in search queries
- supports binary formats like compressed archives, PDFs, eBooks, etc.
- better support for Unicode, special characters, and searching across multiple lines of text
- supports [fuzzy search](https://github.com/Genivia/ugrep#fuzzy)

#### Cons

- not as fast as `sonic` and but also not as simple as `ripgrep`
- not all of its features are fully integrated with ArchiveBox yet

<br/><br/>

<a name="sonic"></a>

### `sonic` ⭐️ (the recommended upgrade path for most people)

[Sonic](https://github.com/valeriansaliou/sonic) is a fast, lightweight, rust-based alternative to super-heavy traditional search backends like Elasticsearch. It is capable of normalizing natural language search queries, fuzzy matching, and searching Unicode, without needing to maintain a duplicate document store index of all the searchable text.

Internally it functions as an index store, storing only the original IDs of the Snapshots with a super-compressed representation of the text. This allows it to scale to searching terabytes of archive data while maintaining an index only a fraction of that size.

*ArchiveBox has supported Sonic for years, and it is the most thoroughly tested and recommended backend for ArchiveBox users that need to scale beyond `ripgrep`.*

Using [sonic with ArchiveBox in Docker Compose](https://github.com/ArchiveBox/ArchiveBox/blob/dev/docker-compose.yml) is the easiest way to get started, though you can also use it without Docker by [installing it manually](https://github.com/valeriansaliou/sonic#installation) and then running `uv tool install --python 3.13 --upgrade 'archivebox[sonic] @ git+https://github.com/ArchiveBox/ArchiveBox.git@dev'`.

```bash
set -euo pipefail; compose_dir="$(mktemp -d)"; compose_file="$compose_dir/docker-compose.yml"; mkdir -p "$compose_dir/data" "$compose_dir/fixture" "$compose_dir/sonic/store/kv" "$compose_dir/sonic/store/fst"; printf '<title>ArchiveBox docs fixture</title> sonic indexed body\n' > "$compose_dir/fixture/sonic-docs"
printf '%s\n' '[server]' 'log_level = "error"' '[channel]' 'inet = "0.0.0.0:1491"' 'tcp_timeout = 300' 'auth_password = "SecretPassword"' '[channel.search]' 'query_limit_default = 10' 'query_limit_maximum = 100' 'query_alternates_try = 4' 'suggest_limit_default = 5' 'suggest_limit_maximum = 20' 'list_limit_default = 100' 'list_limit_maximum = 500' '[store]' '[store.kv]' 'path = "/var/lib/sonic/store/kv/"' 'retain_word_objects = 1000' '[store.kv.pool]' 'inactive_after = 1800' '[store.kv.database]' 'flush_after = 1' 'compress = true' 'parallelism = 2' 'max_files = 100' 'max_compactions = 1' 'max_flushes = 1' 'write_buffer = 16384' 'write_ahead_log = true' '[store.fst]' 'path = "/var/lib/sonic/store/fst/"' '[store.fst.pool]' 'inactive_after = 300' '[store.fst.graph]' 'consolidate_after = 1' 'max_size = 2048' 'max_words = 250000' > "$compose_dir/sonic.cfg"; printf 'services:\n  archivebox:\n    image: archivebox-docs-ci\n    environment:\n      SEARCH_BACKEND_ENGINE: sonic\n      SEARCH_BACKEND_SONIC_HOST_NAME: sonic\n      SEARCH_BACKEND_SONIC_PORT: 1491\n      SEARCH_BACKEND_SONIC_PASSWORD: SecretPassword\n    depends_on:\n      sonic:\n        condition: service_started\n      fixture:\n        condition: service_started\n    volumes:\n      - %s:/data\n  sonic:\n    image: valeriansaliou/sonic:v1.4.9\n    volumes:\n      - %s:/etc/sonic.cfg:ro\n      - %s:/var/lib/sonic/store\n  fixture:\n    image: python:3.13-alpine\n    command: python -m http.server 8000 --directory /fixture\n    volumes:\n      - %s:/fixture:ro\n' "$compose_dir/data" "$compose_dir/sonic.cfg" "$compose_dir/sonic/store" "$compose_dir/fixture" > "$compose_file"
trap 'docker compose -f "$compose_file" down --remove-orphans' EXIT
docker compose -f "$compose_file" up -d sonic fixture
docker compose -f "$compose_file" run --rm archivebox init
docker compose -f "$compose_file" run --rm archivebox add --plugins=wget 'http://fixture:8000/sonic-docs'
docker compose -f "$compose_file" run --rm archivebox update --index-only
sonic_ids="$(docker compose -f "$compose_file" run --rm archivebox shell -c "from archivebox.search.query import iter_query_search_ids; print(*iter_query_search_ids('sonic-docs', search_mode='contents:sonic'))")"; test -n "$sonic_ids"
search_result="$(docker compose -f "$compose_file" run --rm archivebox search --search contents:sonic 'sonic-docs')"; grep -q 'http://fixture:8000/sonic-docs' <<< "$search_result"
docker compose -f "$compose_file" logs sonic
test -f "$compose_dir/data/index.sqlite3"
test -n "$(find "$compose_dir/sonic/store" -type f -print -quit)"
running_services="$(docker compose -f "$compose_file" ps --status running --services)"; grep -qx sonic <<< "$running_services"; grep -qx fixture <<< "$running_services"
docker compose -f "$compose_file" down --remove-orphans
trap - EXIT
test -f "$compose_file"
test -d "$compose_dir/data/archive"
docker image inspect archivebox-docs-ci >/dev/null
docker image inspect valeriansaliou/sonic:v1.4.9 >/dev/null
```

*Fore more detailed instructions [see here](https://github.com/ArchiveBox/ArchiveBox/issues/956#issuecomment-1320587158)...*

#### Pros

- extremely fast, most queries complete in microseconds even with 100k+ snapshots
- maintains lightweight, compressed search index that is minuscule compared to original data
- all-in-one binary written in rust, available cross-platform and easy to deploy
- supports advanced full-text search features like normalization, stemming, etc.
- supports indexing and querying on a remote server (many ArchiveBox instances can share a single `sonic` instance)

#### Cons

- one extra dependency to install and background worker to keep running (Docker Compose makes this easy though)
- does not support searching binary files like PDFs, eBooks, compressed archives, etc.

<br/>

<a name="fts5"></a>

### `SQLite FTS5`

This is a [recently added](https://github.com/ArchiveBox/ArchiveBox/pull/1241) experimental option that uses a separate SQLite3 Database (similar to the one ArchiveBox already uses for Snapshot metadata) to provide full-text search.

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"
archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox add --plugins=mercury "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}"
uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_ENGINE=sqlite
uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_SQLITE_SEPARATE_DATABASE=True
uv run --project "$project_dir" --no-sync archivebox update --index-only
search_result="$(uv run --project "$project_dir" --no-sync archivebox search --search contents:sqlite 'ArchiveBox docs fixture')"; grep -q "${ARCHIVEBOX_DOCS_URL_ONE:-https://example.com/}" <<< "$search_result"
uv run --project "$project_dir" --no-sync abxpkg env --install --lib="$ABXPKG_LIB_DIR" --binproviders env,apt,brew sqlite3 >/dev/null
test -x "$ABXPKG_LIB_DIR/env/bin/sqlite3"
sqlite_tables="$("$ABXPKG_LIB_DIR/env/bin/sqlite3" ./search.sqlite3 '.tables')"; grep -q search_index <<< "$sqlite_tables"
sqlite_count="$("$ABXPKG_LIB_DIR/env/bin/sqlite3" ./search.sqlite3 'SELECT COUNT(*) FROM search_index;')"; grep -Eq '^[1-9][0-9]*$' <<< "$sqlite_count"
```

```bash
set -euo pipefail; project_dir="${ARCHIVEBOX_PROJECT_DIR:-$PWD}"; archivebox_data="$(mktemp -d)"; cd "$archivebox_data"
uv run --project "$project_dir" --no-sync archivebox init
uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_SQLITE_SEPARATE_DATABASE=True
uv run --project "$project_dir" --no-sync archivebox config --set SEARCH_BACKEND_SQLITE_TOKENIZERS="porter unicode61 remove_diacritics 2"
uv run --project "$project_dir" --no-sync archivebox config --get SEARCH_BACKEND_SQLITE_DB
```

- https://www.sqlite.org/fts5.html
- https://github.com/ArchiveBox/ArchiveBox/pull/1241

#### Pros

- No additional dependencies needed to install, SQLite3 is already available and used by ArchiveBox
- No long-running background search worker process needed, 0 idle resource use
- Supports advanced full-text search features like boolean operators, stemming, phrases, etc.
- Comparable speed and efficiency to `sonic` for most use-cases (much faster than `ripgrep`/`ugrep`)
- Durability and portability, SQLite is widely used and supported by every major platform on earth

#### Cons

- Not as thoroughly-tested by ArchiveBox team as our `sonic` or `ripgrep` backends
- Maintains a (compressed, but still potentially large) duplicate copy of all searchable text in `search.sqlite3` db
- Does not support searching binary files PDFs, eBooks, compressed archives, etc.
- Search indexing and querying must be performed on same server as ArchiveBox data (we don't yet support sending FTS5 queries to a remote server)

<br/>

---

<br/>

### Further Reading

- https://github.com/ArchiveBox/ArchiveBox/blob/dev/docker-compose.yml#:~:text=SEARCH_BACKEND_ENGINE
- https://archivebox.github.io/abx-plugins/#search_backend_ripgrep
- https://archivebox.github.io/abx-plugins/#search_backend_sonic
- https://archivebox.github.io/abx-plugins/#search_backend_sqlite

* [#22 Original Issue where full-text search functionality was proposed](https://github.com/ArchiveBox/ArchiveBox/issues/22)
* [#543 + #570 Original PR where full-text search functionality was implemented](https://github.com/ArchiveBox/ArchiveBox/pull/543)
* [#956 Documentation: Document how search works](https://github.com/ArchiveBox/ArchiveBox/issues/956#issuecomment-1320587158)
* [#654 Support: Search Backend only searching admin Snapshot fields instead of archive content](https://github.com/ArchiveBox/ArchiveBox/issues/654)
* [#1087 Support: Help setting up full text search](https://github.com/ArchiveBox/ArchiveBox/issues/1087) 
* [#1091 Support: Help switching to ripgrep-all](https://github.com/ArchiveBox/ArchiveBox/issues/1091)
* [#1318 Troubleshooting: Search times out on v0.7.2 installed on Synology using Portainer](https://github.com/ArchiveBox/ArchiveBox/issues/1318)
* [#1333 + #1316 Text Search and Filters don't work at the same time in the web UI](https://github.com/ArchiveBox/ArchiveBox/pull/1333)
* [#1320 Troubleshooting: Sonic backend Error: ENDED authentication_failed doesn't contain protocol(NUMBER)](https://github.com/ArchiveBox/ArchiveBox/pull/1320)

- [#1139 Feature Request: Add AI-assisted summarization, tagging, search, and more using LLMs / RAG](https://github.com/ArchiveBox/ArchiveBox/issues/1139)
- [#1358 Django Admin general improvements: tree view, better filters, better sorting, custom pages, etc.](https://github.com/ArchiveBox/ArchiveBox/issues/1358)
