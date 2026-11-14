import json
import shutil

import pytest

from archivebox.tests.conftest import run_python_cwd


def test_machine_settings_sources_use_real_overlays(initialized_archive):
    _, stderr, code = run_python_cwd(
        r"""
import os
import django
django.setup()
from archivebox.config.common import get_config, get_config_with_sources, load_source_config, config_field_metadata
from archivebox.config.constants import CONSTANTS
from archivebox.machine.models import Machine

machine = Machine.current()
machine.config.update(TIMEOUT=137, UNRELATED_SETTING={'preserve': ['this']})
machine.save(update_fields=['config'])
os.environ['TIMEOUT'] = '251'
os.environ['SAVE_WGET'] = 'False'
with CONSTANTS.CONFIG_FILE.open('a') as file:
    file.write('\n[TEST_SETTINGS]\nSCREENSHOT_TIMEOUT = 43\n')
before = CONSTANTS.CONFIG_FILE.read_bytes()
stored = dict(machine.config)
values = get_config_with_sources(machine=machine)
assert values['TIMEOUT'] == {'value': 137, 'source': 'Machine'}
assert values['WGET_ENABLED'] == {'value': False, 'source': 'Environment'}
assert values['SCREENSHOT_TIMEOUT'] == {'value': 43, 'source': 'File'}
assert values['WGET_TIMEOUT'] == {'value': 137, 'source': 'Machine'}
assert values['SCREENSHOT_WAIT_FOR_TEXT']['source'] == 'Plugin Default'
baseline = get_config(include_file=False, include_machine=False)
assert baseline.TIMEOUT == 251
assert baseline.SCREENSHOT_TIMEOUT == 251
assert baseline.WGET_ENABLED is False
assert load_source_config(include_file=False).TIMEOUT == 251
metadata = config_field_metadata(include_execution=True)
assert metadata['TIMEOUT']['schema']['type'] == 'integer'
assert metadata['SEARCH_BACKEND_ENGINE']['schema']['type'] == 'string'
assert metadata['URL_ALLOWLIST']['schema']['default'] is None
assert {'type': 'null'} in metadata['URL_ALLOWLIST']['schema']['anyOf']
assert 'SEARCH_BACKEND_ENGINE' not in config_field_metadata()
resolved = get_config(machine=machine).model_dump(mode='json')
assert {key: row['value'] for key, row in values.items()} == resolved
machine.refresh_from_db()
assert machine.config == stored
assert CONSTANTS.CONFIG_FILE.read_bytes() == before
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr


def test_machine_settings_strict_mirror_reports_committed_db_and_preserves_file(initialized_archive):
    _, stderr, code = run_python_cwd(
        """
from pathlib import Path
import django
django.setup()
from django.db import transaction
from archivebox.config.collection import ConfigMirrorError
from archivebox.config.constants import CONSTANTS
from archivebox.config.configset import read_ini_config
from archivebox.machine.models import Machine

machine = Machine.current()
machine.config['UNRELATED_SETTING'] = {'preserve': ['this']}
machine.save(update_fields=['config'], strict_config_mirror=True)
before = CONSTANTS.CONFIG_FILE.read_bytes()
machine.config['TIMEOUT'] = 137
Path.cwd().chmod(0o500)
try:
    try:
        machine.save(update_fields=['config'], strict_config_mirror=True)
    except ConfigMirrorError:
        pass
    else:
        raise AssertionError('Strict save must report the failed file write')
    machine.refresh_from_db()
    assert machine.config['TIMEOUT'] == 137
    assert machine.config['UNRELATED_SETTING'] == {'preserve': ['this']}
    assert CONSTANTS.CONFIG_FILE.read_bytes() == before
    machine.config['TIMEOUT'] = 138
    machine.save(update_fields=['config'])
    machine.refresh_from_db()
    assert machine.config['TIMEOUT'] == 138
    assert CONSTANTS.CONFIG_FILE.read_bytes() == before
    try:
        with transaction.atomic():
            machine.config['TIMEOUT'] = 137
            machine.save(update_fields=['config'], strict_config_mirror=True)
    except ConfigMirrorError:
        pass
    else:
        raise AssertionError('Strict mirror failure must escape the enclosing commit')
    machine.refresh_from_db()
    assert machine.config['TIMEOUT'] == 137
    assert CONSTANTS.CONFIG_FILE.read_bytes() == before
finally:
    Path.cwd().chmod(0o700)
machine.save(update_fields=['config'], strict_config_mirror=True)
assert read_ini_config(CONSTANTS.CONFIG_FILE)['TIMEOUT'] == '137'
before = CONSTANTS.CONFIG_FILE.read_bytes()
with transaction.atomic():
    machine.config['TIMEOUT'] = 138
    machine.save(update_fields=['config'], strict_config_mirror=True)
    assert CONSTANTS.CONFIG_FILE.read_bytes() == before
    transaction.set_rollback(True)
machine.refresh_from_db()
assert machine.config['TIMEOUT'] == 137
assert CONSTANTS.CONFIG_FILE.read_bytes() == before
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr


def test_explicit_plugin_scope_overrides_enable_default(initialized_archive):
    from abx_plugins import get_plugins_dir

    plugin = initialized_archive / "custom_plugins" / "opencode"
    shutil.copytree(get_plugins_dir() / "opencode", plugin)
    schema_file = plugin / "config.json"
    schema = json.loads(schema_file.read_text())
    schema["properties"]["OPENCODE_ENABLED"]["x-scope"] = "server"
    schema_file.write_text(json.dumps(schema))
    _, stderr, code = run_python_cwd(
        """
from archivebox.config.common import ArchiveBoxConfig, PLUGIN_CONFIG_SCHEMAS
assert PLUGIN_CONFIG_SCHEMAS['opencode']['properties']['OPENCODE_ENABLED']['x-scope'] == 'server'
assert ArchiveBoxConfig.scope_for_key('OPENCODE_ENABLED') == 'server'
assert ArchiveBoxConfig.scope_for_key('WGET_ENABLED') == 'crawl_execution'
assert ArchiveBoxConfig.scope_for_key('WGET_WARC_ENABLED') == 'crawl_frozen'
assert 'OPENCODE_ENABLED' not in ArchiveBoxConfig._crawl_runtime_keys()
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr


def test_machine_settings_form_preserves_redacted_and_untouched_values(initialized_archive):
    _, stderr, code = run_python_cwd(
        """
import django
django.setup()
from django.http import QueryDict
from archivebox.config.common import get_config
from archivebox.config.forms import MachineSettingsForm
from archivebox.machine.models import Machine

machine = Machine.current()
baseline = get_config(include_file=False, include_machine=False)
machine.config.update(TIMEOUT=baseline.TIMEOUT, TWOCAPTCHA_API_KEY='keep-this-secret', UNRELATED_SETTING={'keep': [42]})
machine.save(update_fields=['config'])
stored = dict(machine.config)
unchanged = QueryDict('', mutable=True)
unchanged['plugin_config__base__TIMEOUT'] = str(baseline.TIMEOUT)
form = MachineSettingsForm(unchanged, machine=machine)
assert form.is_valid(), form.errors
assert form.cleaned_data['config'] == stored
data = QueryDict('', mutable=True)
data.update(settings_editor='1', settings_changed='TWOCAPTCHA_API_KEY', plugin_config__twocaptcha__TWOCAPTCHA_API_KEY='********')
form = MachineSettingsForm(data, machine=machine)
assert form.is_valid(), form.errors
assert form.cleaned_data['config'] == stored
data['settings_changed'] = 'TIMEOUT'
data['plugin_config__base__TIMEOUT'] = str(baseline.TIMEOUT + 1)
form = MachineSettingsForm(data, machine=machine)
assert form.is_valid(), form.errors
assert form.cleaned_data['config'] == {**stored, 'TIMEOUT': baseline.TIMEOUT + 1}
for key in ('URL_ALLOWLIST', 'URL_DENYLIST'):
    invalid = QueryDict('', mutable=True)
    invalid.update(settings_editor='1', settings_changed=key)
    invalid['plugin_config__archivebox__' + key] = '['
    form = MachineSettingsForm(invalid, machine=machine)
    assert not form.is_valid(), f'{key} must compile before saving'
    assert key in str(form.errors), form.errors
machine.refresh_from_db()
assert machine.config == stored
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr


def test_persona_settings_form_rejects_invalid_runtime_core_values(initialized_archive):
    _, stderr, code = run_python_cwd(
        """
import json
import django
django.setup()
from django.http import QueryDict
from archivebox.personas.forms import PersonaAdminForm
from archivebox.personas.models import Persona

persona = Persona.objects.create(name='Validation Review', config={'PERMISSIONS': 'private', 'UNRELATED_SETTING': {'keep': [42]}})
data = QueryDict('', mutable=True)
data.update(name=persona.name, permissions='private', config=json.dumps(persona.config), import_mode='none', settings_editor='1', settings_changed='DELETE_AFTER', plugin_config__archivebox__DELETE_AFTER='tomorrow')
form = PersonaAdminForm(data, instance=persona)
assert not form.is_valid(), 'Invalid runtime duration must not be saved'
assert 'DELETE_AFTER' in str(form.errors), form.errors
persona.refresh_from_db()
assert persona.config == {'PERMISSIONS': 'private', 'UNRELATED_SETTING': {'keep': [42]}}
""",
        cwd=initialized_archive,
    )
    assert code == 0, stderr


@pytest.mark.parametrize("kind", ["machine", "persona"])
def test_settings_resets_resolve_sibling_overrides_and_pending_edits(initialized_archive, kind):
    _, stderr, code = run_python_cwd(
        """
import json
import django
django.setup()
from django.http import QueryDict
from archivebox.config.common import get_config
from archivebox.config.forms import MachineSettingsForm
from archivebox.machine.models import Machine
from archivebox.personas.forms import PersonaAdminForm
from archivebox.personas.models import Persona

kind = SUBJECT_KIND
subject = Machine.current() if kind == 'machine' else Persona.objects.create(name='Sibling Defaults', config={'PERMISSIONS': 'private'})
initial = {**subject.config, 'TIMEOUT': 120, 'WGET_TIMEOUT': 90, 'UNRELATED_SETTING': {'keep': [42]}}
cases = [
    ({'WGET_TIMEOUT': 60}, 120, 60, True),
    ({'WGET_TIMEOUT': 120}, 120, 120, False),
    ({'TIMEOUT': 180, 'WGET_TIMEOUT': 180}, 180, 180, False),
    ({'TIMEOUT': 180, 'WGET_TIMEOUT': 60}, 180, 60, True),
]
for edits, expected_timeout, expected_wget_timeout, explicit in cases:
    subject.config = dict(initial)
    subject.save(update_fields=['config'])
    data = QueryDict('', mutable=True)
    data['settings_editor'] = '1'
    data.setlist('settings_changed', list(edits))
    for key, value in edits.items():
        plugin = 'base' if key == 'TIMEOUT' else 'wget'
        data[f'plugin_config__{plugin}__{key}'] = str(value)
    if kind == 'persona':
        data.update(name=subject.name, permissions='private', config=json.dumps(subject.config), import_mode='none', created_by=str(subject.created_by_id))
        form = PersonaAdminForm(data, instance=subject)
    else:
        form = MachineSettingsForm(data, machine=subject)
    assert form.is_valid(), (kind, edits, form.errors)
    merged = form.cleaned_data['config']
    assert ('WGET_TIMEOUT' in merged) is explicit, (kind, edits, merged.get('WGET_TIMEOUT'))
    if explicit:
        assert merged['WGET_TIMEOUT'] == expected_wget_timeout, (kind, edits, merged)
    assert merged['TIMEOUT'] == expected_timeout
    assert merged['UNRELATED_SETTING'] == {'keep': [42]}
    if kind == 'persona':
        form.save()
    else:
        subject.config = merged
        subject.save(update_fields=['config'], strict_config_mirror=True)
    subject.refresh_from_db()
    assert subject.config == merged
    resolved = get_config(**{kind: subject})
    assert resolved.TIMEOUT == expected_timeout, (kind, edits)
    assert resolved.WGET_TIMEOUT == expected_wget_timeout, (kind, edits)
""".replace("SUBJECT_KIND", repr(kind)),
        cwd=initialized_archive,
    )
    assert code == 0, stderr
