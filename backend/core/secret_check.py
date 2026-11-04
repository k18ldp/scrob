"""Startup sanity check for SECRET_KEY.

The key signs every login token, so anyone who knows it can forge a login for
any user. Copy-pasted placeholders from sample configs are refused outright;
short keys only get a warning so existing installs are not locked out.
"""
import logging

PLACEHOLDERS = frozenset({
    "changeme", "change-me", "change_me", "changethis", "change-this",
    "secret", "secretkey", "secret_key", "secret-key", "your-secret-key",
    "your_secret_key", "yoursecretkey", "password", "default", "example",
    "test", "dev", "none", "null",
})
MIN_RECOMMENDED_LENGTH = 32
HOW_TO_FIX = "Generate one with `openssl rand -hex 32` and set it as SECRET_KEY."


def is_placeholder(secret_key: str) -> bool:
    return (secret_key or "").strip().lower() in PLACEHOLDERS


def check_secret_key(secret_key: str, logger: logging.Logger) -> None:
    """Raise RuntimeError for an empty or placeholder key; warn if it is short."""
    value = (secret_key or "").strip()
    if not value or is_placeholder(value):
        raise RuntimeError(
            "SECRET_KEY is empty or a well-known placeholder, so anyone could forge "
            "a login. Refusing to start. " + HOW_TO_FIX
        )
    if len(value) < MIN_RECOMMENDED_LENGTH:
        logger.warning(
            "SECRET_KEY is only %d characters; use at least %d. %s",
            len(value), MIN_RECOMMENDED_LENGTH, HOW_TO_FIX,
        )
