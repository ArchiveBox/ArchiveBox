import os

import pytest
from pydantic import ValidationError

from archivebox.config import CONSTANTS


def test_sonic_dir_is_allowed_inside_data_dir():
    assert "sonic" in CONSTANTS.ALLOWED_IN_DATA_DIR


def test_resolved_config_validation_does_not_reload_environment():
    from archivebox.config.common import ArchiveBoxConfig

    previous_timeout = os.environ.get("TIMEOUT")
    try:
        os.environ["TIMEOUT"] = "1"
        assert ArchiveBoxConfig().TIMEOUT == 1
        assert ArchiveBoxConfig.model_validate_resolved({}).TIMEOUT != 1
    finally:
        if previous_timeout is None:
            os.environ.pop("TIMEOUT", None)
        else:
            os.environ["TIMEOUT"] = previous_timeout


def test_resolved_config_validation_matches_normal_validation():
    from archivebox.config.common import ArchiveBoxConfig

    payload = ArchiveBoxConfig().model_dump(mode="json")
    payload.update(
        {
            "TIMEOUT": "17",
            "CHROME_ARGS": ["--headless", "--no-sandbox"],
            "ABXPKG_LIB_DIR": "./lib-from-resolved-validation",
        },
    )

    normally_validated = ArchiveBoxConfig.model_validate(payload)
    resolved_validated = ArchiveBoxConfig.model_validate_resolved(payload)

    assert resolved_validated.model_dump(mode="json") == normally_validated.model_dump(mode="json")
    assert resolved_validated.model_fields_set == normally_validated.model_fields_set


def test_resolved_config_validation_preserves_validation_errors():
    from archivebox.config.common import ArchiveBoxConfig

    with pytest.raises(ValidationError) as normal_error:
        ArchiveBoxConfig.model_validate({"TIMEOUT": "not-an-integer"})
    with pytest.raises(ValidationError) as resolved_error:
        ArchiveBoxConfig.model_validate_resolved({"TIMEOUT": "not-an-integer"})

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
