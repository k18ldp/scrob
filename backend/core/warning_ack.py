"""Acknowledged sync warnings, kept per connection.

The browser fingerprints the set of warnings it is showing; acknowledging stores
that fingerprint, and the banner stays collapsed while the fingerprint is
unchanged. Any new or different warning changes it, so the banner comes back.
"""
import re
from typing import Optional

KINDS = ("pull", "push")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{8,32}$")


def clean_fingerprint(value: Optional[str]) -> Optional[str]:
    """The fingerprint if it is a short lowercase hex string, else None."""
    if isinstance(value, str) and _FINGERPRINT_RE.match(value):
        return value
    return None


def with_ack(current: Optional[dict], kind: str, fingerprint: Optional[str]) -> dict:
    """A copy of ``current`` with ``kind`` set to ``fingerprint`` (None clears it)."""
    if kind not in KINDS:
        raise ValueError("unknown warning kind")
    out = {k: v for k, v in (current or {}).items() if k in KINDS and clean_fingerprint(v)}
    if fingerprint is None:
        out.pop(kind, None)
    else:
        cleaned = clean_fingerprint(fingerprint)
        if cleaned is None:
            raise ValueError("invalid fingerprint")
        out[kind] = cleaned
    return out
