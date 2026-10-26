import pytest
from pydantic import SecretStr, ValidationError

from restock.config import Settings

VALID_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/restock"
VALID_SALT = SecretStr("a" * 32)


def make_settings(
    *,
    database_url: str = VALID_DATABASE_URL,
    reporter_hash_salt: SecretStr = VALID_SALT,
    log_level: str = "INFO",
    default_timezone: str = "America/New_York",
    discord_token: SecretStr | None = None,
    local_restock_channel_id: int | None = None,
) -> Settings:
    return Settings(
        _env_file=None,
        database_url=database_url,
        reporter_hash_salt=reporter_hash_salt,
        log_level=log_level,
        default_timezone=default_timezone,
        discord_token=discord_token,
        local_restock_channel_id=local_restock_channel_id,
    )


def test_settings_normalize_log_level() -> None:
    settings = make_settings(log_level="debug")
    assert settings.log_level == "DEBUG"


def test_settings_reject_non_psycopg_database_url() -> None:
    with pytest.raises(ValidationError, match="postgresql\\+psycopg"):
        make_settings(database_url="postgresql://user:password@localhost/restock")


def test_settings_reject_short_salt() -> None:
    with pytest.raises(ValidationError, match="at least 16"):
        make_settings(reporter_hash_salt=SecretStr("short"))


def test_settings_reject_unknown_timezone() -> None:
    with pytest.raises(ValidationError, match="Unknown IANA timezone"):
        make_settings(default_timezone="Mars/Olympus_Mons")


def test_settings_allow_optional_restock_channel() -> None:
    assert make_settings().local_restock_channel_id is None
    assert make_settings(local_restock_channel_id=123456789).local_restock_channel_id == 123456789
    with pytest.raises(ValidationError):
        make_settings(local_restock_channel_id=0)


def test_secrets_are_not_exposed_in_repr() -> None:
    settings = make_settings(discord_token=SecretStr("super-secret-token"))
    assert "super-secret-token" not in repr(settings)
