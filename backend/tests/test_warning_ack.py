import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-bytes-long")

import pytest

from core.warning_ack import clean_fingerprint, with_ack


def test_fingerprint_validation():
    assert clean_fingerprint("1a2b3c4d5e6f") == "1a2b3c4d5e6f"
    for bad in ["", "ABCDEF12", "xyz12345", "a" * 33, "1234567", None, 5, "<script>"]:
        assert clean_fingerprint(bad) is None


def test_with_ack_sets_and_keeps_other_kind():
    out = with_ack({"pull": "aaaaaaaa"}, "push", "bbbbbbbb")
    assert out == {"pull": "aaaaaaaa", "push": "bbbbbbbb"}


def test_with_ack_replaces_and_clears():
    assert with_ack({"pull": "aaaaaaaa"}, "pull", "cccccccc") == {"pull": "cccccccc"}
    assert with_ack({"pull": "aaaaaaaa"}, "pull", None) == {}


def test_with_ack_drops_junk_already_stored():
    assert with_ack({"pull": "<bad>", "other": "aaaaaaaa"}, "push", "bbbbbbbb") == {"push": "bbbbbbbb"}


def test_with_ack_rejects_bad_input():
    with pytest.raises(ValueError):
        with_ack({}, "other", "aaaaaaaa")
    with pytest.raises(ValueError):
        with_ack({}, "pull", "NOT-HEX")
