#!/usr/bin/env python3
"""Tests for per-crawl Persona runtime profile management."""

import json
import textwrap

import pytest

from .conftest import run_python_cwd


@pytest.mark.parametrize("operation", ["snapshot", "snapshot_alias", "crawl_alias"])
def test_runtime_rejects_template_overlap_before_mutating_files(initialized_archive, operation):
    script = textwrap.dedent(
        """
        import json
        from pathlib import Path
        import django
        django.setup()
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona = Persona.objects.create(name='PreserveProfile')
        persona.ensure_dirs()
        sentinel = Path(persona.CHROME_USER_DATA_DIR) / 'keep.txt'
        sentinel.write_text('saved browser session')
        crawl = Crawl.objects.create(urls='https://example.com', persona=persona)
        snapshot = Snapshot.objects.create(url='https://example.com', crawl=crawl)
        operation = OPERATION
        if operation == 'crawl_alias':
            local_root = persona.local_runtime_root_for_crawl(crawl)
            local_root.parent.parent.mkdir(parents=True, exist_ok=True)
            local_root.parent.symlink_to(persona.path.parent, target_is_directory=True)
            output = crawl.output_dir
        elif operation == 'snapshot_alias':
            alias = Path.cwd() / 'profile-alias'
            alias.symlink_to(persona.path.parent, target_is_directory=True)
            local_root = alias / persona.name
            output = snapshot.output_dir
        else:
            local_root = persona.path
            output = snapshot.output_dir
        error = ''
        try:
            if operation == 'crawl_alias':
                persona.prepare_runtime_for_crawl(crawl)
            else:
                persona.prepare_runtime_for_snapshot(snapshot, local_root=local_root)
        except ValueError as exc:
            error = str(exc)
        print(json.dumps({
            'source': sentinel.read_text() if sentinel.exists() else None,
            'error': error,
            'archive_link_created': (output / '.persona').is_symlink(),
            'lock_created': (persona.path / '.archivebox-crawl-profile.lock').exists(),
        }))
        """,
    ).replace("OPERATION", repr(operation))
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr
    result = json.loads(stdout.strip().splitlines()[-1])
    assert result["source"] == "saved browser session"
    assert "overlap" in result["error"].lower()
    assert result["archive_link_created"] is False
    assert result["lock_created"] is False


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


@pytest.mark.parametrize("use_template", [False, True])
@pytest.mark.parametrize("existing_crawl_runtime", [False, True])
def test_snapshot_runtime_authentication_requires_selected_persona(initialized_archive, use_template, existing_crawl_runtime):
    script = (
        textwrap.dedent(
            """
        import hashlib
        import json
        import os
        from pathlib import Path

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()
        from archivebox.core.models import Snapshot
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        persona = Persona.get_or_create_default()
        persona.ensure_dirs()
        profile = Path(persona.CHROME_USER_DATA_DIR)
        preferences = profile / 'Default' / 'Preferences'
        preferences.parent.mkdir(parents=True, exist_ok=True)
        preferences.write_text('{"profile": {"name": "Saved authenticated profile"}}')
        cookies = '# Netscape HTTP Cookie File\\n.example.com\\tTRUE\\t/\\tFALSE\\t2147483647\\tsession\\tprivate\\n'
        auth = json.dumps({'cookies': [], 'origins': [{'origin': 'https://example.com', 'localStorage': [{'name': 'session', 'value': 'private'}]}]})
        (persona.path / 'cookies.txt').write_text(cookies)
        (persona.path / 'auth.json').write_text(auth)
        with persona.lock_runtime_for_crawl():
            pass
        def files(root):
            return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in root.rglob('*') if path.is_file()}
        original = files(persona.path)
        crawl = Crawl.objects.create(urls='https://example.com', persona=persona if USE_TEMPLATE else None)
        snapshot = Snapshot.objects.create(url='https://example.com', crawl=crawl)

        # Anonymous crawl preparation must ignore every saved authentication source.
        config = persona.prepare_runtime_for_crawl(crawl, use_template=False)
        runtime = persona.local_runtime_root_for_crawl(crawl)
        assert list((runtime / 'chrome_profile').iterdir()) == []
        assert not (runtime / 'cookies.txt').exists()
        assert not (runtime / 'auth.json').exists()
        assert 'COOKIES_FILE' not in config and 'AUTH_STORAGE_FILE' not in config
        persona.cleanup_runtime_for_crawl(crawl)

        if EXISTING_CRAWL_RUNTIME:
            # A previously authenticated crawl runtime must not authorize an anonymous snapshot.
            persona.prepare_runtime_for_crawl(crawl, use_template=True)
            (runtime / 'chrome_profile' / 'Default' / 'Preferences').write_text('{"profile": {"name": "Existing crawl profile"}}')
        runtime_before = files(runtime) if runtime.exists() else {}
        config = persona.prepare_runtime_for_snapshot(snapshot, use_template=USE_TEMPLATE)
        root = persona.runtime_root_for_snapshot(snapshot).resolve()
        if USE_TEMPLATE:
            source = runtime if EXISTING_CRAWL_RUNTIME else persona.path
            assert (root / 'chrome_profile' / 'Default' / 'Preferences').read_bytes() == (source / 'chrome_profile' / 'Default' / 'Preferences').read_bytes()
            assert Path(config['COOKIES_FILE']).read_text() == cookies
            assert Path(config['AUTH_STORAGE_FILE']).read_text() == auth
        else:
            assert list((root / 'chrome_profile').iterdir()) == []
            assert not (root / 'cookies.txt').exists()
            assert not (root / 'auth.json').exists()
            assert not (root / 'template_dir.txt').exists()
            assert 'COOKIES_FILE' not in config and 'AUTH_STORAGE_FILE' not in config
        assert files(persona.path) == original
        assert (files(runtime) if runtime.exists() else {}) == runtime_before
        persona.cleanup_runtime_for_crawl(crawl)
        assert not root.exists()
        print('selected-persona-authentication-preserved')
        """,
        )
        .replace("USE_TEMPLATE", repr(use_template))
        .replace("EXISTING_CRAWL_RUNTIME", repr(existing_crawl_runtime))
    )
    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stdout + stderr
    assert "selected-persona-authentication-preserved" in stdout


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


@pytest.mark.parametrize("isolation", ["crawl", "snapshot"])
@pytest.mark.parametrize("persona_selection", ["null", "deleted", "explicit"])
def test_cli_capture_without_persona_never_uses_default_template(
    initialized_archive,
    browser_runtime,
    httpserver,
    isolation,
    persona_selection,
):
    import hashlib
    from pathlib import Path

    from playwright.sync_api import sync_playwright

    from .conftest import cli_env, run_archivebox_cmd

    httpserver.expect_request("/favicon.ico").respond_with_data("", content_type="image/x-icon")
    httpserver.expect_request("/seed").respond_with_data(
        "<script>document.cookie='template_secret=private; path=/; max-age=3600'; "
        "localStorage.setItem('template_secret', 'private');</script>",
        content_type="text/html",
    )
    httpserver.expect_request("/capture").respond_with_data(
        "<body><script>document.body.textContent = 'A captured page must preserve the selected browser identity without inheriting any unselected saved authentication state. cookie=' + document.cookie + "
        "'; storage=' + localStorage.getItem('template_secret'); "
        "document.cookie='capture_write=runtime; path=/; max-age=3600'; "
        "localStorage.setItem('capture_write', 'runtime');</script></body>",
        content_type="text/html",
    )
    env = cli_env(
        ABXPKG_LIB_DIR=str(browser_runtime["lib_dir"]),
        CHROME_BINARY=str(browser_runtime["chrome_binary"]),
        CHROME_HEADLESS="True",
        CHROME_ISOLATION=isolation,
        PLUGINS="dom",
        DOM_ENABLED="True",
        PERSONAS_DIR=str(initialized_archive / "personas"),
    )
    prepare = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import json; from archivebox.personas.models import Persona; from archivebox.crawls.models import Crawl; "
            "p=Persona.get_or_create_default(); p.ensure_dirs(); "
            "selected = p if " + repr(persona_selection) + " == 'explicit' else "
            "Persona.objects.create(name='DeletedCapturePersona') if " + repr(persona_selection) + " == 'deleted' else None; "
            "c=Crawl.objects.create(urls="
            + repr(httpserver.url_for("/capture"))
            + ", persona=selected, config={'PLUGINS':'dom','CHROME_ISOLATION':"
            + repr(isolation)
            + "}); "
            "selected.delete() if " + repr(persona_selection) + " == 'deleted' else None; "
            "print(json.dumps({'crawl_id':str(c.pk),'template':p.CHROME_USER_DATA_DIR}))",
        ],
        cwd=initialized_archive,
        env=env,
    )
    assert prepare.returncode == 0, prepare.stdout + prepare.stderr
    prepared = json.loads(prepare.stdout.strip().splitlines()[-1])
    template = Path(prepared["template"])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch_persistent_context(
            str(template),
            executable_path=str(browser_runtime["chrome_binary"]),
            headless=True,
            args=browser_runtime["chrome_args"],
        )
        page = browser.new_page()
        page.goto(httpserver.url_for("/seed"))
        assert page.evaluate("localStorage.getItem('template_secret')") == "private"
        browser.close()

    def profile_bytes():
        return {
            str(path.relative_to(template)): hashlib.sha256(path.read_bytes()).hexdigest() for path in template.rglob("*") if path.is_file()
        }

    original_profile = profile_bytes()
    captured = run_archivebox_cmd(["run", "--crawl-id=" + prepared["crawl_id"]], cwd=initialized_archive, env=env, timeout=120)
    assert captured.returncode == 0, captured.stdout + captured.stderr
    output = run_archivebox_cmd(
        [
            "manage",
            "shell",
            "-c",
            "import json; from archivebox.crawls.models import Crawl; c=Crawl.objects.get(pk=" + repr(prepared["crawl_id"]) + "); "
            "from archivebox.personas.models import Persona; s=c.snapshot_set.get(); runtime=(c.persona or Persona(name='Default')).local_runtime_root_for_crawl(c); "
            "print(json.dumps({'persona_id':str(c.persona_id),'output':str(s.output_dir), 'status':s.status, 'crawl_output':str(c.output_dir), 'runtime':str(runtime)}))",
        ],
        cwd=initialized_archive,
        env=env,
    )
    assert output.returncode == 0, output.stdout + output.stderr
    result = json.loads(output.stdout.strip().splitlines()[-1])
    saved = (Path(result["output"]) / "dom" / "output.html").read_text()
    assert result["status"] == "sealed"
    crawl_output = Path(result["crawl_output"])
    browser_output = Path(result["output"]) if isolation == "snapshot" else crawl_output
    assert str(template) not in (browser_output / "chrome" / "cmd.sh").read_text()
    assert not (Path(result["output"]) / ".persona").is_symlink()
    assert not (crawl_output / ".persona").exists()
    assert not (crawl_output / ".persona").is_symlink()
    assert not Path(result["runtime"]).parent.parent.exists()
    if persona_selection == "explicit":
        assert "cookie=template_secret=private; storage=private" in saved
    else:
        assert result["persona_id"] == "None"
        assert "cookie=; storage=null" in saved
        assert "template_secret=private" not in saved
    assert profile_bytes() == original_profile, "Capture modified the saved Default browser template"
