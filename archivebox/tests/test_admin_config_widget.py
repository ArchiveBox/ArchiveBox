from archivebox.base_models.admin import KeyValueWidget


def test_key_value_widget_renders_enum_autocomplete_metadata(monkeypatch):
    monkeypatch.setattr(
        KeyValueWidget,
        '_get_config_options',
        lambda self: {
            'CHROME_WAIT_FOR': {
                'plugin': 'chrome',
                'type': 'string',
                'default': 'networkidle2',
                'description': 'Page load completion condition',
                'enum': ['domcontentloaded', 'load', 'networkidle0', 'networkidle2'],
            },
        },
    )

    html = str(
        KeyValueWidget().render(
            'config',
            {'CHROME_WAIT_FOR': 'load'},
            attrs={'id': 'id_config'},
        )
    )

    assert '"enum": ["domcontentloaded", "load", "networkidle0", "networkidle2"]' in html
    assert 'class="kv-value-options"' in html
    assert 'class="kv-help"' in html
    assert 'configureValueInput_id_config' in html
    assert 'describeMeta_id_config' in html
    assert 'validateValueAgainstMeta_id_config' in html


def test_key_value_widget_renders_numeric_and_pattern_constraints(monkeypatch):
    monkeypatch.setattr(
        KeyValueWidget,
        '_get_config_options',
        lambda self: {
            'TIMEOUT': {
                'plugin': 'base',
                'type': 'integer',
                'default': 60,
                'description': 'Timeout in seconds',
                'minimum': 5,
                'maximum': 120,
            },
            'CHROME_RESOLUTION': {
                'plugin': 'chrome',
                'type': 'string',
                'default': '1440,2000',
                'description': 'Viewport resolution',
                'pattern': '^\\d+,\\d+$',
            },
        },
    )

    html = str(KeyValueWidget().render('config', {}, attrs={'id': 'id_config'}))

    assert '"minimum": 5' in html
    assert '"maximum": 120' in html
    assert '"pattern": "^\\\\d+,\\\\d+$"' in html
    assert 'Expected: ' in html
    assert 'Example: ' in html
    assert 'setValueValidationState_id_config' in html
    assert 'coerceValueForStorage_id_config' in html


def test_key_value_widget_accepts_common_boolean_spellings(monkeypatch):
    monkeypatch.setattr(
        KeyValueWidget,
        '_get_config_options',
        lambda self: {
            'DEBUG': {
                'plugin': 'base',
                'type': 'boolean',
                'default': False,
                'description': 'Enable debug mode',
            },
        },
    )

    html = str(KeyValueWidget().render('config', {'DEBUG': 'True'}, attrs={'id': 'id_config'}))

    assert "enumValues = ['True', 'False']" in html
    assert "raw.toLowerCase()" in html
    assert "lowered === 'true' || raw === '1'" in html
    assert "lowered === 'false' || raw === '0'" in html


def test_key_value_widget_shows_array_and_object_examples_and_binary_rules(monkeypatch):
    monkeypatch.setattr(
        KeyValueWidget,
        '_get_config_options',
        lambda self: {
            'WGET_ARGS_EXTRA': {
                'plugin': 'wget',
                'type': 'array',
                'default': [],
                'description': 'Extra arguments to append to wget command',
            },
            'SAVE_ALLOWLIST': {
                'plugin': 'base',
                'type': 'object',
                'default': {},
                'description': 'Regex allowlist mapped to enabled methods',
            },
            'WGET_BINARY': {
                'plugin': 'wget',
                'type': 'string',
                'default': 'wget',
                'description': 'Path to wget binary',
            },
        },
    )

    html = str(KeyValueWidget().render('config', {}, attrs={'id': 'id_config'}))

    assert 'Example: ["--extra-arg"]' in html
    assert 'Example: {"^https://example\\\\.com": ["wget"]}' in html
    assert 'Example: wget or /usr/bin/wget' in html
    assert 'validateBinaryValue_id_config' in html
    assert "meta.key.endsWith('_BINARY')" in html
    assert "Binary paths cannot contain quotes" in html


def test_key_value_widget_falls_back_to_binary_validation_for_unknown_binary_keys(monkeypatch):
    monkeypatch.setattr(
        KeyValueWidget,
        '_get_config_options',
        lambda self: {
            'CHROME_BINARY': {
                'plugin': 'base',
                'type': 'string',
                'default': '',
                'description': 'Resolved Chromium/Chrome binary path shared across plugins',
            },
        },
    )

    html = str(
        KeyValueWidget().render(
            'config',
            {'NODE_BINARY': '/opt/homebrew/bin/node'},
            attrs={'id': 'id_config'},
        )
    )

    assert 'function getMetaForKey_id_config' in html
    assert "if (key.endsWith('_BINARY'))" in html
    assert 'Path to binary executable' in html
