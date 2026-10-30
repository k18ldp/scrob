# Emby and Jellyfin share the same REST API — functions are re-exported, except
# mark_watched, which differs: Emby's PlayedItems endpoint rejects the ISO 8601
# DatePlayed Jellyfin accepts (HTTP 500, FormatException) and needs yyyyMMddHHmmss.
from datetime import datetime

import httpx

from core.jellyfin import (
    validate_connection,
    get_libraries,
    get_movies,
    get_shows,
    get_episodes,
    get_item,
    get_items_batch,
    get_items_watched_state,
    extract_quality,
    find_movie_by_tmdb_id,
    find_episode_by_ids,
    find_episode_in_series,
    build_tmdb_index,
    build_tvdb_index,
    mark_unwatched,
    set_rating,
    scan_libraries,
    EMBY_DATE_PLAYED_FORMAT,
    mark_watched as _mark_watched,
)


async def mark_watched(url: str, token: str, user_id: str, item_id: str, client: httpx.AsyncClient | None = None, played_at: datetime | None = None) -> bool:
    """Mark an Emby item as played, stamped with the original watch date (UTC) in Emby's format."""
    return await _mark_watched(
        url, token, user_id, item_id,
        client=client, played_at=played_at, date_format=EMBY_DATE_PLAYED_FORMAT,
    )
