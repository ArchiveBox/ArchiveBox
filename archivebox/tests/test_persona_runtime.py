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
        runtime_profile = Path(overrides['CHROME_USER_DATA_DIR'])
        runtime_downloads = Path(overrides['CHROME_DOWNLOADS_DIR'])

        print(json.dumps({
            'runtime_root_exists': runtime_root.exists(),
            'runtime_profile_exists': runtime_profile.exists(),
            'runtime_downloads_exists': runtime_downloads.exists(),
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
    assert payload["preferences_copied"] is True
    assert payload["singleton_removed"] is True
    assert payload["cache_removed"] is True
    assert payload["log_removed"] is True
    assert payload["persona_name_recorded"] == "Default"
    assert payload["template_dir_recorded"].endswith("/personas/Default/chrome_user_data")
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


def test_crawl_resolve_persona_raises_for_missing_persona_id(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os
        from uuid import uuid4

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        crawl = Crawl.objects.create(urls='https://example.com', persona_id=uuid4())

        try:
            crawl.resolve_persona()
        except Persona.DoesNotExist as err:
            print(json.dumps({'raised': True, 'message': str(err)}))
        else:
            raise SystemExit('resolve_persona unexpectedly succeeded')
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["raised"] is True
    assert "references missing Persona" in payload["message"]


def test_get_config_raises_for_missing_persona_id(initialized_archive):
    script = textwrap.dedent(
        """
        import json
        import os
        from uuid import uuid4

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'archivebox.core.settings')
        import django
        django.setup()

        from archivebox.config.configset import get_config
        from archivebox.crawls.models import Crawl
        from archivebox.personas.models import Persona

        crawl = Crawl.objects.create(urls='https://example.com', persona_id=uuid4())

        try:
            get_config(crawl=crawl)
        except Persona.DoesNotExist as err:
            print(json.dumps({'raised': True, 'message': str(err)}))
        else:
            raise SystemExit('get_config unexpectedly succeeded')
        """,
    )

    stdout, stderr, code = run_python_cwd(script, cwd=initialized_archive, timeout=60)
    assert code == 0, stderr

    payload = json.loads(stdout.strip().splitlines()[-1])
    assert payload["raised"] is True
    assert "references missing Persona" in payload["message"]
