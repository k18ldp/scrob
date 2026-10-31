"""Which media-server connection a pushed item id belongs to."""


def file_belongs_to_connection(file_connection_id: int | None, connection_id: int) -> bool:
    """A library file's server item id only means something on the connection it was read from.

    Rows from before connection tracking have no connection id; those keep the older
    behaviour of applying to any connection of the same type.
    """
    return file_connection_id is None or file_connection_id == connection_id


def media_needing_lookup(
    connection_ids: list[int], media_ids: list[int], mapped: set[tuple[int | None, int]]
) -> dict[int, list[int]]:
    """For each connection, the media that has no known server item id on it yet.

    ``mapped`` holds ``(connection_id, media_id)`` for every library file already known;
    a ``None`` connection id (legacy row) counts as known on every connection.
    """
    out: dict[int, list[int]] = {}
    for conn_id in connection_ids:
        missing = [m for m in media_ids if (conn_id, m) not in mapped and (None, m) not in mapped]
        if missing:
            out[conn_id] = missing
    return out
