import logging
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes-long")

import pytest

from core.secret_check import check_secret_key

log = logging.getLogger("secret-check-test")


@pytest.mark.parametrize("bad", ["changeme", "ChangeMe", "  changeme  ", "secret", "", "   "])
def test_placeholders_and_empty_are_refused(bad):
    with pytest.raises(RuntimeError, match="Refusing to start"):
        check_secret_key(bad, log)


def test_short_key_warns_but_starts(caplog):
    with caplog.at_level(logging.WARNING, logger=log.name):
        check_secret_key("a-short-but-unique-key", log)
    assert "characters" in caplog.text


def test_long_random_key_is_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=log.name):
        check_secret_key("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", log)
    assert caplog.text == ""
