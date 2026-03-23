__package__ = "archivebox.machine"

import json
import shlex
from typing import Any


SENSITIVE_ENV_KEY_PARTS = ("KEY", "TOKEN", "SECRET")


def stringify_env_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "True" if value else "False"
    return json.dumps(value, separators=(",", ":"))


def is_redacted_env_key(key: str) -> bool:
    upper_key = str(key or "").upper()
    return any(part in upper_key for part in SENSITIVE_ENV_KEY_PARTS)


def redact_env(env: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(env, dict):
        return {}
    return {
        str(key): value
        for key, value in env.items()
        if key is not None and not is_redacted_env_key(str(key))
    }


def env_to_dotenv_text(env: dict[str, Any] | None) -> str:
    redacted_env = redact_env(env)
    return "\n".join(
        f"{key}={shlex.quote(stringify_env_value(value))}"
        for key, value in sorted(redacted_env.items())
        if value is not None
    )


def env_to_shell_exports(env: dict[str, Any] | None) -> str:
    redacted_env = redact_env(env)
    return " ".join(
        f"{key}={shlex.quote(stringify_env_value(value))}"
        for key, value in sorted(redacted_env.items())
        if value is not None
    )
