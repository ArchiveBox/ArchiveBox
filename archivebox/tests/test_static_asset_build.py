"""Build fingerprints follow the installed tree and catalog, regardless of release."""

from archivebox.core.static_asset_build import read_static_asset_build, write_static_asset_build


def test_static_asset_build_reuses_installed_tree(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_static_asset_build(first)
    write_static_asset_build(second)

    key = read_static_asset_build(first)
    assert key and key.startswith("assets-")
    assert read_static_asset_build(second) == key
    assert read_static_asset_build(tmp_path / "missing.json") is None


def test_static_asset_build_covers_catalog(tmp_path, settings):
    english = tmp_path / "english.json"
    french = tmp_path / "french.json"
    write_static_asset_build(english)
    english_key = read_static_asset_build(english)
    assert english_key

    settings.LANGUAGE_CODE = "fr"
    assert read_static_asset_build(english) is None
    write_static_asset_build(french)
    french_key = read_static_asset_build(french)
    assert french_key and french_key != english_key


def test_static_asset_build_excludes_custom_templates(tmp_path, settings):
    manifest = tmp_path / "static.json"
    write_static_asset_build(manifest)
    assert read_static_asset_build(manifest)

    custom_static = tmp_path / "custom_templates" / "static"
    custom_static.mkdir(parents=True)
    (custom_static / "admin.css").write_text("body { color: red; }\n")
    settings.STATICFILES_DIRS = [str(custom_static), *settings.STATICFILES_DIRS]
    settings.CUSTOM_TEMPLATES_ENABLED = True
    assert read_static_asset_build(manifest) is None


def test_static_asset_build_excludes_different_finders(tmp_path, settings):
    manifest = tmp_path / "static.json"
    write_static_asset_build(manifest)
    assert read_static_asset_build(manifest)

    settings.STATICFILES_FINDERS = ["django.contrib.staticfiles.finders.FileSystemFinder"]
    assert read_static_asset_build(manifest) is None
