import os
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from app.core.config import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_settings_use_safe_development_defaults_without_env_file(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("APP_ENV", raising=False)
    settings = Settings(_env_file=None)

    assert settings.app_env == "development"
    assert settings.api_host == "127.0.0.1"


def test_invalid_app_env_is_rejected_by_real_app_import() -> None:
    environment = os.environ.copy()
    environment["APP_ENV"] = "invalid-environment"

    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "app_env" in result.stderr.lower()
    assert "validation error" in result.stderr.lower()


def test_invalid_app_env_is_rejected_by_settings_model() -> None:
    try:
        Settings(app_env="invalid-environment", _env_file=None)
    except ValidationError as error:
        assert "app_env" in str(error)
    else:
        raise AssertionError("Invalid APP_ENV was accepted")
