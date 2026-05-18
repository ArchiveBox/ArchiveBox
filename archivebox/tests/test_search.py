import os
from pathlib import Path

from benedict import benedict


def test_search_backend_env_exposes_resolved_runtime_config(monkeypatch, tmp_path):
    from archivebox.search import search_backend_env

    monkeypatch.setenv("SEARCH_BACKEND_SONIC_HOST_NAME", "old-host")
    config = benedict(
        {
            "DATA_DIR": tmp_path,
            "USERS_DIR": tmp_path / "archive" / "users",
            "SEARCH_BACKEND_ENGINE": "sonic",
            "SEARCH_BACKEND_SONIC_HOST_NAME": "sonic",
            "SEARCH_BACKEND_SONIC_PORT": 1491,
            "SEARCH_BACKEND_SONIC_PASSWORD": "SecretPassword",
            "USE_INDEXING_BACKEND": True,
            "IGNORED_NONE_VALUE": None,
        },
    )

    with search_backend_env(config=config):
        assert os.environ["DATA_DIR"] == str(tmp_path)
        assert os.environ["SNAP_DIR"] == str(Path(tmp_path) / "archive" / "users")
        assert os.environ["SEARCH_BACKEND_ENGINE"] == "sonic"
        assert os.environ["SEARCH_BACKEND_SONIC_HOST_NAME"] == "sonic"
        assert os.environ["SEARCH_BACKEND_SONIC_PORT"] == "1491"
        assert os.environ["SEARCH_BACKEND_SONIC_PASSWORD"] == "SecretPassword"
        assert os.environ["USE_INDEXING_BACKEND"] == "True"
        assert "IGNORED_NONE_VALUE" not in os.environ

    assert os.environ["SEARCH_BACKEND_SONIC_HOST_NAME"] == "old-host"
