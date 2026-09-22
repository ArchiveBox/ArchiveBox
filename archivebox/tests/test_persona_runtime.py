#!/usr/bin/env python3
"""Tests for per-crawl Persona runtime profile management."""

import json
import textwrap

from .conftest import run_python_cwd


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
    assert payload["singleton_removed"] is True
    assert payload["cache_removed"] is True
    assert payload["log_removed"] is True
    assert payload["persona_name_recorded"] == "Default"
    assert payload["template_dir_recorded"].endswith("/personas/Default/chrome_profile")
    assert payload["chrome_binary_recorded"] == "/Applications/Chromium.app/Contents/MacOS/Chromium"


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

        persona.cleanup_runtime_for_crawl(crawl)

        print(json.dumps({
            'runtime_removed': not runtime_root.exists(),
            'template_still_exists': (template_dir / 'Default' / 'Preferences').exists(),
        }))
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["runtime_removed"] is True
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
        runtime_config = runner.load_snapshot_payload(str(snapshot.id))['config']

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
    assert payload["snap_dir"] == payload["expected_snap_dir"]
    assert payload["crawl_dir"] == payload["expected_crawl_dir"]
    assert payload["active_persona"] == "StackPersona"
