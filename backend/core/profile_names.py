def unique_username(base: str, taken_lower: set[str], max_len: int = 60) -> str:
    """A username based on ``base`` that isn't in ``taken_lower`` (lower-cased names in use)."""
    base = " ".join((base or "").split())[:max_len] or "Profile"
    if base.lower() not in taken_lower:
        return base
    n = 2
    while f"{base} {n}".lower() in taken_lower:
        n += 1
    return f"{base} {n}"
