#!/usr/bin/env python3
"""Tests for per-crawl Persona runtime profile management."""

import json
import textwrap

import pytest

from .conftest import run_python_cwd


@pytest.mark.parametrize("parser", ["url_list", "jsonl"])
def test_empty_duplicate_crawl_does_not_prepare_persona_runtime(initialized_archive, parser):
    script = textwrap.dedent(
        """
        import asyncio
        import json
        import os
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona
        from archivebox.services.runner import CrawlRunner

        parser = PARSER_VALUE
        url = 'https://example.com/already-archived'
        existing_crawl = Crawl.objects.create(urls=url, status='sealed', retry_at=None)
        existing = Snapshot.objects.create(url=url, crawl=existing_crawl, status='sealed', retry_at=None)
        persona = Persona.objects.create(name='EmptyCrawlPersona')
        persona.ensure_dirs()
        preferences = Path(persona.CHROME_USER_DATA_DIR) / 'Default' / 'Preferences'
        preferences.parent.mkdir(parents=True, exist_ok=True)
        preferences.write_text('{"profile": {"name": "preserve-original"}}')
        crawl = Crawl.objects.create(
            urls=json.dumps({'url': url}) if parser == 'jsonl' else url,
            persona=persona,
            config={'ONLY_NEW': True, 'PARSER': parser, 'PLUGINS': 'hashes'},
        )
        runner = CrawlRunner(crawl)
        try:
            snapshot_ids = runner.load_run_state()
            print(json.dumps({
                'snapshot_ids': snapshot_ids,
                'new_snapshots': crawl.snapshot_set.count(),
                'existing_snapshot_id': str(Snapshot.objects.get(url=url).id),
                'expected_existing_id': str(existing.id),
                'runtime_created': persona.runtime_root_for_crawl(crawl).exists(),
                'runtime_link_created': persona.runtime_root_for_crawl(crawl).parent.is_symlink(),
                'local_runtime_created': persona.local_runtime_root_for_crawl(crawl).exists(),
                'preferences': json.loads(preferences.read_text()),
            }))
        finally:
            asyncio.run(runner.bus.destroy(clear=False))
        """,
    ).replace("PARSER_VALUE", repr(parser))
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr
    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["snapshot_ids"] == []
    assert payload["new_snapshots"] == 0
    assert payload["existing_snapshot_id"] == payload["expected_existing_id"]
    assert payload["preferences"] == {"profile": {"name": "preserve-original"}}
    assert payload["runtime_created"] is False
    assert payload["runtime_link_created"] is False
    assert payload["local_runtime_created"] is False


def test_persona_prepare_runtime_for_crawl_clones_and_cleans_profile(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona, _ = Persona.objects.get_or_create(name='Default')
        persona.ensure_dirs()

        template_dir = Path(persona.CHROME_USER_DATA_DIR)
        (template_dir / 'SingletonLock').write_text('locked')
        (template_dir / 'chrome.log').write_text('noise')
        (template_dir / 'Default' / 'GPUCache').mkdir(parents=True, exist_ok=True)
        (template_dir / 'Default' / 'GPUCache' / 'blob').write_text('cached')
        (template_dir / 'Default' / 'Preferences').write_text('{"ok": true}')
        (template_dir / 'Default' / 'Sessions').mkdir()
        (template_dir / 'Default' / 'Sessions' / 'Session_1').write_bytes(b'session-state')
        (template_dir / 'Default' / 'Current Session').write_bytes(b'legacy-session-state')

        crawl = Crawl.objects.create(urls='https://example.com', persona_id=persona.id)
        overrides = persona.prepare_runtime_for_crawl(
            crawl,
            chrome_binary='/Applications/Chromium.app/Contents/MacOS/Chromium',
        )

        runtime_root = persona.runtime_root_for_crawl(crawl)
        runtime_profile = persona.runtime_profile_dir_for_crawl(crawl)
        runtime_downloads = persona.runtime_downloads_dir_for_crawl(crawl)

        print(json.dumps({
            'runtime_root_exists': runtime_root.exists(),
            'runtime_profile_exists': runtime_profile.exists(),
            'runtime_downloads_exists': runtime_downloads.exists(),
            'runtime_personas_dir': overrides['PERSONAS_DIR'],
            'active_persona': overrides['ACTIVE_PERSONA'],
            'preferences_copied': (runtime_profile / 'Default' / 'Preferences').exists(),
            'sessions_preserved': (runtime_profile / 'Default' / 'Sessions' / 'Session_1').read_bytes() == b'session-state',
            'legacy_session_preserved': (runtime_profile / 'Default' / 'Current Session').read_bytes() == b'legacy-session-state',
            'singleton_removed': not (runtime_profile / 'SingletonLock').exists(),
            'cache_removed': not (runtime_profile / 'Default' / 'GPUCache').exists(),
            'log_removed': not (runtime_profile / 'chrome.log').exists(),
            'persona_name_recorded': (runtime_root / 'persona_name.txt').read_text().strip(),
            'template_dir_recorded': (runtime_root / 'template_dir.txt').read_text().strip(),
            'chrome_binary_recorded': (runtime_root / 'chrome_binary.txt').read_text().strip(),
        }))
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["runtime_root_exists"] is True
    assert payload["runtime_profile_exists"] is True
    assert payload["runtime_downloads_exists"] is True
    assert payload["runtime_personas_dir"].endswith("/.persona")
    assert payload["active_persona"] == "Default"
    assert payload["preferences_copied"] is True
    assert payload["sessions_preserved"] is True
    assert payload["legacy_session_preserved"] is True
    assert payload["singleton_removed"] is True
    assert payload["cache_removed"] is True
    assert payload["log_removed"] is True
    assert payload["persona_name_recorded"] == "Default"
    assert payload["template_dir_recorded"].endswith("/personas/Default/chrome_profile")
    assert payload["chrome_binary_recorded"] == "/Applications/Chromium.app/Contents/MacOS/Chromium"


@pytest.mark.parametrize("preferences_state", ["valid", "secure", "missing", "malformed"])
def test_persona_runtime_does_not_clone_uninstalled_extension_storage(initialized_archive, preferences_state):
    script = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona = Persona.objects.create(name='ExtensionStorage')
        persona.ensure_dirs()
        profile = Path(persona.CHROME_USER_DATA_DIR) / 'Default'
        profile.mkdir(parents=True, exist_ok=True)
        installed_id, removed_id = 'a' * 32, 'b' * 32
        # Public identity from a real Chromium install; lazy extensions can have
        # no current Preferences entry after their private install path expires.
        managed_id = 'bpgdakjikjpceenapeanibleafagicgk'
        keys = profile.parent / 'archivebox-extension-keys'
        keys.mkdir()
        (keys / 'managed.pub').write_text('MCowBQYDK2VwAyEAyKayg73K/vV28N0zj7bava/TtQVm7DwGMKlW6uM5/NA=')
        files = [
            f'IndexedDB/chrome-extension_{installed_id}_0.indexeddb.leveldb/000001.log',
            f'IndexedDB/chrome-extension_{removed_id}_0.indexeddb.leveldb/000001.log',
            f'IndexedDB/chrome-extension_{removed_id}_0.indexeddb.blob/1/1',
            'IndexedDB/https_example.com_0.indexeddb.leveldb/000001.log',
            'Service Worker/ScriptCache/script',
            f'Local Extension Settings/{installed_id}/000001.log',
            f'Local Extension Settings/{removed_id}/000001.log',
            f'IndexedDB/chrome-extension_{managed_id}_0.indexeddb.leveldb/000001.log',
            f'Local Extension Settings/{managed_id}/000001.log',
        ]
        for name in files:
            path = profile / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'preserve source contents')
        preferences = profile / 'Preferences'
        state = PREFERENCES_STATE
        if state in ('valid', 'secure'):
            if state == 'secure':
                preferences.write_text('{"extensions": {"settings": {}}}')
                preferences = profile / 'Secure Preferences'
            preferences.write_text(json.dumps({'extensions': {'settings': {
                installed_id: {'path': '/installed/extension', 'state': 0},
                removed_id: {},
            }}}))
        elif state == 'malformed':
            preferences.write_text('{incomplete')
        else:
            preferences.unlink(missing_ok=True)
        crawl = Crawl.objects.create(urls='https://example.com', persona=persona)
        persona.prepare_runtime_for_crawl(crawl)
        runtime = persona.runtime_profile_dir_for_crawl(crawl) / 'Default'
        print(json.dumps({
            'copied': [(runtime / name).exists() for name in files],
            'source_preserved': all((profile / name).read_bytes() == b'preserve source contents' for name in files),
            'retained_contents': all((runtime / name).read_bytes() == b'preserve source contents'
                for name in files if (runtime / name).exists()),
        }))
        """,
    ).replace("PREFERENCES_STATE", repr(preferences_state))
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr
    payload = json.loads(stdout.strip().splitlines()[-1])
    keep_unknown_extension = preferences_state not in ("valid", "secure")
    assert payload["copied"] == [True, keep_unknown_extension, keep_unknown_extension, True, True, True, keep_unknown_extension, True, True]
    assert payload["source_preserved"] is True
    assert payload["retained_contents"] is True


@pytest.mark.parametrize("isolation", ["crawl", "snapshot"])
def test_persona_cleanup_does_not_load_unprepared_backlog(initialized_archive, isolation):
    script = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()
        from django.db.models.signals import post_init
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona = Persona.objects.create(name='BoundedCleanup')
        crawl = Crawl.objects.create(urls='https://example.com', persona=persona)
        snapshots = [Snapshot.objects.create(url=f'https://example.com/{i}', crawl=crawl) for i in range(12)]
        persona.prepare_runtime_for_crawl(crawl)
        prepared = snapshots[:2] if ISOLATION == 'snapshot' else []
        for snapshot in prepared:
            persona.prepare_runtime_for_snapshot(snapshot)
        local = persona.local_runtime_root_for_crawl(crawl).parent.parent
        seen = []
        def observe(sender, instance, **kwargs):
            seen.append(str(instance.id))
        post_init.connect(observe, sender=Snapshot)
        try:
            persona.cleanup_runtime_for_crawl(Crawl.objects.get(pk=crawl.pk))
        finally:
            post_init.disconnect(observe, sender=Snapshot)
        print(json.dumps({
            'loaded': sorted(seen),
            'prepared': sorted(str(snapshot.id) for snapshot in prepared),
            'local_removed': not local.exists(),
            'links_removed': all(not persona.runtime_root_for_snapshot(snapshot).parent.is_symlink() for snapshot in prepared),
            'crawl_link_removed': not persona.runtime_root_for_crawl(crawl).parent.is_symlink(),
            'template_preserved': Path(persona.CHROME_USER_DATA_DIR).exists(),
            'backlog_count': crawl.snapshot_set.count(),
        }))
        """,
    ).replace("ISOLATION", repr(isolation))
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr
    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["loaded"] == payload["prepared"]
    assert payload["local_removed"] and payload["links_removed"] and payload["crawl_link_removed"]
    assert payload["template_preserved"]
    assert payload["backlog_count"] == 12


def test_persona_cleanup_runtime_for_crawl_removes_only_runtime_copy(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona, _ = Persona.objects.get_or_create(name='Default')
        persona.ensure_dirs()
        template_dir = Path(persona.CHROME_USER_DATA_DIR)
        (template_dir / 'Default').mkdir(parents=True, exist_ok=True)
        (template_dir / 'Default' / 'Preferences').write_text('{"kept": true}')

        crawl = Crawl.objects.create(urls='https://example.com', persona_id=persona.id)
        persona.prepare_runtime_for_crawl(crawl)
        runtime_root = persona.runtime_root_for_crawl(crawl)
        local_runtime_root = runtime_root.resolve()

        persona.cleanup_runtime_for_crawl(crawl)

        print(json.dumps({
            'runtime_removed': not runtime_root.exists(),
            'local_runtime_removed': not local_runtime_root.exists(),
            'runtime_link_removed': not runtime_root.parent.is_symlink(),
            'template_still_exists': (template_dir / 'Default' / 'Preferences').exists(),
        }))
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["runtime_removed"] is True
    assert payload["local_runtime_removed"] is True
    assert payload["runtime_link_removed"] is True
    assert payload["template_still_exists"] is True


def test_crawl_runner_respects_chrome_isolation_config(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.crawls.models import Crawl
        from archivebox.services.runner import CrawlRunner

        crawl_default = Crawl.objects.create(urls='https://example.com')
        runner_default = CrawlRunner(crawl_default)
        runner_default.load_run_state()

        crawl_snapshot = Crawl.objects.create(
            urls='https://example.com/explicit',
            config={'CHROME_ISOLATION': 'snapshot'},
        )
        runner_snapshot = CrawlRunner(crawl_snapshot)
        runner_snapshot.load_run_state()

        print(json.dumps({
            'default_isolation': runner_default.base_config.get('CHROME_ISOLATION'),
            'explicit_isolation': runner_snapshot.base_config.get('CHROME_ISOLATION'),
        }))
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["default_isolation"] == "crawl"
    assert payload["explicit_isolation"] == "snapshot"


def test_crawl_resolve_persona_treats_missing_persona_id_as_null(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona = Persona.objects.create(name='TemporaryPersona')
        crawl = Crawl.objects.create(urls='https://example.com', persona_id=persona.id)
        persona.delete()
        crawl.refresh_from_db()

        print(json.dumps({'persona': crawl.resolve_persona(), 'persona_id': crawl.persona_id}))
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["persona"] is None
    assert payload["persona_id"] is None


def test_get_config_treats_missing_persona_id_as_null(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.config.common import get_config
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona = Persona.objects.create(name='TemporaryPersona')
        crawl = Crawl.objects.create(
            urls='https://example.com',
            persona_id=persona.id,
            config={'DEFAULT_PERSONA': 'Default'},
        )
        persona.delete()
        crawl.refresh_from_db()

        config = get_config(crawl=crawl)
        print(json.dumps({'timeout': config.TIMEOUT, 'persona_id': str(crawl.persona_id)}))
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["timeout"]
    assert payload["persona_id"] == "None"


def test_get_config_resolves_parent_scopes_for_snapshot_runtime(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        os.environ['TIMEOUT'] = '22'
        os.environ['CHROME_BINARY'] = 'env-chrome'

        import django
        django.setup()

        from archivebox.config import CONSTANTS
        from archivebox.config.common import get_config
        from archivebox.core.models import ArchiveResult, Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.machine.models import Machine
        from archivebox.personas.models import Persona
        from archivebox.services.runner import CrawlRunner

        CONSTANTS.CONFIG_FILE.write_text('[ARCHIVING_CONFIG]\\nTIMEOUT=11\\nCHROME_BINARY=file-chrome\\n')

        machine = Machine.current()
        machine.config = {'CHROME_BINARY': 'machine-chrome'}
        machine.save(update_fields=['config'])

        persona = Persona.objects.create(
            name='StackPersona',
            config={'TIMEOUT': 33, 'CHROME_BINARY': 'persona-chrome'},
        )
        persona.ensure_dirs()
        crawl = Crawl.objects.create(
            urls='https://example.com',
            persona_id=persona.id,
            config={'TIMEOUT': 44, 'CHROME_BINARY': 'crawl-chrome'},
        )
        persona.config = {'TIMEOUT': 99, 'CHROME_BINARY': 'persona-chrome-updated'}
        persona.save(update_fields=['config'])
        snapshot = Snapshot.objects.create(
            url='https://example.com',
            crawl=crawl,
            config={'TIMEOUT': 55, 'CHROME_BINARY': 'snapshot-chrome'},
        )
        result = ArchiveResult.objects.create(
            snapshot=snapshot,
            plugin='title',
        )

        env_config = get_config(include_machine=False)
        machine_config = get_config(machine=machine)
        persona_config = get_config(persona=persona)
        crawl_config = get_config(crawl=crawl)
        snapshot_config = get_config(snapshot=snapshot)
        override_config = get_config(snapshot=snapshot, overrides={'TIMEOUT': 77, 'CHROME_BINARY': 'override-chrome'})
        runner = CrawlRunner(crawl, selected_plugins=['title'], show_progress=False)
        runner.load_run_state()
        from asgiref.sync import async_to_sync
        runtime_config = async_to_sync(runner.load_snapshot_payload)(str(snapshot.id))['config']

        print(json.dumps({
            'env': [env_config.TIMEOUT, env_config.CHROME_BINARY],
            'machine': [machine_config.TIMEOUT, machine_config.CHROME_BINARY],
            'persona': [persona_config.TIMEOUT, persona_config.CHROME_BINARY],
            'crawl': [crawl_config.TIMEOUT, crawl_config.CHROME_BINARY],
            'snapshot': [snapshot_config.TIMEOUT, snapshot_config.CHROME_BINARY],
            'override': [override_config.TIMEOUT, override_config.CHROME_BINARY],
            'snap_dir': str(runtime_config['SNAP_DIR']),
            'expected_snap_dir': str(snapshot.output_dir),
            'crawl_dir': str(runtime_config['CRAWL_DIR']),
            'expected_crawl_dir': str(crawl.output_dir),
            'active_persona': runtime_config['ACTIVE_PERSONA'],
            'runtime_personas_dir': runtime_config['PERSONAS_DIR'],
            'expected_runtime_personas_dir': str(persona.local_runtime_root_for_crawl(crawl).parent),
        }, default=str))
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["env"] == [22, "env-chrome"]
    assert payload["machine"] == [22, "machine-chrome"]
    assert payload["persona"] == [99, "persona-chrome-updated"]
    assert payload["crawl"] == [44, "persona-chrome-updated"]
    assert payload["snapshot"] == [55, "persona-chrome-updated"]
    assert payload["override"] == [77, "persona-chrome-updated"]
    assert payload["runtime_personas_dir"] == payload["expected_runtime_personas_dir"]
    assert payload["snap_dir"] == payload["expected_snap_dir"]
    assert payload["crawl_dir"] == payload["expected_crawl_dir"]
    assert payload["active_persona"] == "StackPersona"


@pytest.mark.parametrize("isolation", ["crawl", "snapshot"])
def test_persona_profile_io_uses_local_storage_and_preserves_archive_link(initialized_archive, isolation):
    script = textwrap.dedent(
        """
        import json
        import os
        import sys
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona = Persona.objects.create(name='LocalProfileIO')
        persona.ensure_dirs()
        template = Path(persona.CHROME_USER_DATA_DIR)
        script = template / 'Default' / 'Service Worker' / 'ScriptCache' / 'script'
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_bytes(b'preserve service worker source')
        (persona.path / 'cookies.txt').write_text('# Netscape HTTP Cookie File\\n')
        (persona.path / 'auth.json').write_text('{"cookies": [], "origins": []}')
        crawl = Crawl.objects.create(urls='https://example.com', persona=persona)
        snapshot = Snapshot.objects.create(url='https://example.com', crawl=crawl)
        events = []
        def audit(event, args):
            if event in ('shutil.copytree', 'shutil.copyfile', 'shutil.rmtree', 'os.scandir', 'open'):
                events.append((event, [str(arg) for arg in args[:2]]))
        sys.addaudithook(audit)
        overrides = persona.prepare_runtime_for_crawl(crawl)
        root = persona.runtime_root_for_crawl(crawl)
        if ISOLATION == 'snapshot':
            overrides = persona.prepare_runtime_for_snapshot(snapshot)
            root = persona.runtime_root_for_snapshot(snapshot)
        preparation_events = list(events)
        local = root.resolve()
        archive_roots = [str(crawl.output_dir), str(snapshot.output_dir)]
        remote_io = [(event, args) for event, args in preparation_events
            if any(arg.startswith(prefix + '/.persona/') for arg in args for prefix in archive_roots)]
        linked = root.parent.is_symlink() and not local.is_symlink()
        local_config = Path(overrides['PERSONAS_DIR']) == local.parent
        contents = (root / 'chrome_profile' / 'Default' / 'Service Worker' / 'ScriptCache' / 'script').read_bytes()
        auth = Path(overrides['AUTH_STORAGE_FILE']).read_text()
        cookies = Path(overrides['COOKIES_FILE']).read_text()
        persona.cleanup_runtime_for_crawl(crawl)
        print(json.dumps({
            'remote_io': remote_io, 'linked': linked, 'local_config': local_config,
            'contents': contents.decode(), 'auth': auth, 'cookies': cookies,
            'local_removed': not local.exists(), 'link_removed': not root.parent.is_symlink(),
            'template_preserved': script.read_bytes() == contents,
        }))
        """,
    ).replace("ISOLATION", repr(isolation))
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr
    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["remote_io"] == []
    assert payload["linked"] is True
    assert payload["local_config"] is True
    assert payload["contents"] == "preserve service worker source"
    assert json.loads(payload["auth"]) == {"cookies": [], "origins": []}
    assert payload["cookies"] == "# Netscape HTTP Cookie File\n"
    assert payload["local_removed"] is True
    assert payload["link_removed"] is True
    assert payload["template_preserved"] is True
