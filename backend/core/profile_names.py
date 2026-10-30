def unique_username(base: str, taken_lower: set[str], max_len: int = 60) -> str:
    """A username based on ``base`` that isn't in ``taken_lower`` (lower-cased names in use)."""
    base = " ".join((base or "").split())[:max_len] or "Profile"
    if base.lower() not in taken_lower:
        return base
    n = 2
    while f"{base} {n}".lower() in taken_lower:
        n += 1
    return f"{base} {n}"


def same_server(a: str | None, b: str | None) -> bool:
    """True when two media-server URLs point at the same server (ignores case and a trailing slash)."""
    return (a or "").rstrip("/").lower() == (b or "").rstrip("/").lower()


def normalize_user_id(value) -> str:
    """Emby/Jellyfin user ids are GUIDs that show up with and without dashes."""
    return str(value or "").replace("-", "").strip().lower()


def pick_linked_connection(connections, server_url: str | None, event_user_id):
    """The connection (``.url``, ``.server_user_id``) linked to this server user, or None.

    Used to route one shared webhook to the right profile. Only a connection on
    the same server whose stored user id matches exactly is accepted - an event
    with no user id, or for a user nobody is linked to, matches nothing.
    """
    wanted = normalize_user_id(event_user_id)
    if not wanted:
        return None
    for conn in connections:
        if normalize_user_id(conn.server_user_id) == wanted and same_server(conn.url, server_url):
            return conn
    return None
