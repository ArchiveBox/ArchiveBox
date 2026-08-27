import os

import pytest
from pydantic import ValidationError

from archivebox.config import CONSTANTS


def test_sonic_dir_is_allowed_inside_data_dir():
    assert "sonic" in CONSTANTS.ALLOWED_IN_DATA_DIR


def test_runtime_config_model_is_separate_from_source_loading():
    from pydantic_settings import BaseSettings
    from archivebox.config.common import ArchiveBoxConfig, ArchiveBoxSourceSettings, get_all_configs

    previous_timeout = os.environ.get("TIMEOUT")
    try:
        os.environ["TIMEOUT"] = "1"
        assert ArchiveBoxSourceSettings().TIMEOUT == 1
        assert ArchiveBoxConfig().TIMEOUT != 1
        assert get_all_configs()["ARCHIVING_CONFIG"].TIMEOUT == 1
        assert not issubclass(ArchiveBoxConfig, BaseSettings)
        assert issubclass(ArchiveBoxSourceSettings, BaseSettings)
    finally:
        if previous_timeout is None:
            os.environ.pop("TIMEOUT", None)
        else:
            os.environ["TIMEOUT"] = previous_timeout


def test_runtime_config_validation_matches_source_model_validation():
    from archivebox.config.common import ArchiveBoxConfig, ArchiveBoxSourceSettings

    payload = ArchiveBoxConfig().model_dump(mode="json")
    payload.update(
        {
            "TIMEOUT": "17",
            "CHROME_ARGS": ["--headless", "--no-sandbox"],
            "ABXPKG_LIB_DIR": "./lib-from-resolved-validation",
        },
    )

    normally_validated = ArchiveBoxSourceSettings.model_validate(payload)
    resolved_validated = ArchiveBoxConfig.model_validate(payload)

    assert resolved_validated.model_dump(mode="json") == normally_validated.model_dump(mode="json")
    assert resolved_validated.model_fields_set == normally_validated.model_fields_set


def test_runtime_config_validation_preserves_source_model_errors():
    from archivebox.config.common import ArchiveBoxConfig, ArchiveBoxSourceSettings

    with pytest.raises(ValidationError) as normal_error:
        ArchiveBoxSourceSettings.model_validate({"TIMEOUT": "not-an-integer"})
    with pytest.raises(ValidationError) as resolved_error:
        ArchiveBoxConfig.model_validate({"TIMEOUT": "not-an-integer"})

    assert resolved_error.value.errors(include_url=False) == normal_error.value.errors(include_url=False)


def test_string_config_values_are_decoded_at_one_boundary():
    from archivebox.config.common import ArchiveBoxConfig
    from archivebox.config.configset import decode_config_inputs

    decoded = decode_config_inputs(
        ArchiveBoxConfig,
        {
            "CHROME_ARGS": '["--headless", "--no-sandbox"]',
            "UNKNOWN_COMPLEX": '{"source": "plugin"}',
        },
        decode_unknown_json=True,
    )

    assert decoded["CHROME_ARGS"] == ["--headless", "--no-sandbox"]
    assert decoded["UNKNOWN_COMPLEX"] == {"source": "plugin"}


def test_resolving_scoped_config_does_not_mutate_process_environment(tmp_path):
    from archivebox.config.common import ArchiveBoxConfig, get_config

    active_lib_dir = tmp_path / "active-lib"
    stale_lib_dir = tmp_path / "stale-lib"
    previous_lib_dir = os.environ.get("ABXPKG_LIB_DIR")
    try:
        os.environ["ABXPKG_LIB_DIR"] = str(active_lib_dir)
        stale_process_config = ArchiveBoxConfig(ABXPKG_LIB_DIR=stale_lib_dir)

        resolved = get_config(base_config=stale_process_config, include_machine=False, resolve_plugins=False)

        assert resolved.ABXPKG_LIB_DIR == stale_lib_dir
        assert os.environ["ABXPKG_LIB_DIR"] == str(active_lib_dir)
    finally:
        if previous_lib_dir is None:
            os.environ.pop("ABXPKG_LIB_DIR", None)
        else:
            os.environ["ABXPKG_LIB_DIR"] = previous_lib_dir
