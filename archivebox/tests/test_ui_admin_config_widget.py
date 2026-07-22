from archivebox.base_models.admin import KeyValueWidget


def test_key_value_widget_renders_enum_autocomplete_metadata():
    html = str(
        KeyValueWidget().render(
            "config",
            {"CHROME_WAIT_FOR": "load"},
            attrs={"id": "id_config"},
        ),
    )

    assert '"enum": ["domcontentloaded", "load", "networkidle0", "networkidle2"]' in html
    assert 'class="kv-value-options"' in html
    assert 'class="kv-help"' in html
    assert "configureValueInput_id_config" in html
    assert "describeMeta_id_config" in html
    assert "validateValueAgainstMeta_id_config" in html


def test_key_value_widget_renders_numeric_and_pattern_constraints():
    html = str(KeyValueWidget().render("config", {}, attrs={"id": "id_config"}))

    assert '"minimum": 0' in html
    assert '"pattern": "^\\\\d+,\\\\d+$"' in html
    assert "Expected: " in html
    assert "Example: " in html
    assert "setValueValidationState_id_config" in html
    assert "coerceValueForStorage_id_config" in html


def test_key_value_widget_accepts_common_boolean_spellings():
    html = str(KeyValueWidget().render("config", {"CHECK_SSL_VALIDITY": "True"}, attrs={"id": "id_config"}))

    assert "enumValues = ['True', 'False']" in html
    assert "raw.toLowerCase()" in html
    assert "lowered === 'true' || raw === '1'" in html
    assert "lowered === 'false' || raw === '0'" in html


def test_key_value_widget_shows_array_and_object_examples_and_binary_rules():
    html = str(KeyValueWidget().render("config", {"NODE_BINARY": "node"}, attrs={"id": "id_config"}))

    assert 'Example: ["--extra-arg"]' in html
    assert "Example: wget or /usr/bin/wget" in html
    assert "validateBinaryValue_id_config" in html
    assert "meta.key.endsWith('_BINARY')" in html
    assert "Binary paths cannot contain quotes" in html


def test_key_value_widget_falls_back_to_binary_validation_for_unknown_binary_keys():
    html = str(
        KeyValueWidget().render(
            "config",
            {"NODE_BINARY": "/opt/homebrew/bin/node"},
            attrs={"id": "id_config"},
        ),
    )

    assert "function getMetaForKey_id_config" in html
    assert "if (key.endsWith('_BINARY'))" in html
    assert "Path to binary executable" in html
