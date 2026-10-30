# Emby and Jellyfin share the same REST API — functions are re-exported, except
# mark_watched, which differs: Emby's PlayedItems endpoint rejects the ISO 8601
# DatePlayed Jellyfin accepts (HTTP 500, FormatException) and needs yyyyMMddHHmmss.
from datetime import datetime

import httpx

from core.jellyfin import (
    _auth_headers,
    PUSH_TIMEOUT,
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


TICKS_PER_SECOND = 10_000_000
# An Emby position within this many seconds of ours (or further ahead) is left
# alone, so a push never drags a resume point backwards.
POSITION_TOLERANCE_SECONDS = 5


async def set_playback_position(url: str, token: str, user_id: str, item_id: str, position_seconds: int, client: httpx.AsyncClient | None = None) -> str:
    """Write a resume position onto an Emby item so it shows in Continue Watching.

    Returns "pushed", "skipped" or "failed". Nothing is written when the item is
    already played, when Emby's own position is already at (or beyond) ours, or
    when the position would be at/after the end of the item (that would be a
    finished play, which is mark_watched's job, not a resume point).

    POST .../UserData replaces the *entire* UserData object rather than patching
    it, so the current UserData is fetched first and merged - same approach as
    set_rating - otherwise Played/PlayCount/IsFavorite/Rating would be reset.
    """
    try:
        position_seconds = int(position_seconds)
    except (TypeError, ValueError):
        return "skipped"
    if position_seconds <= 0:
        return "skipped"
    ticks = position_seconds * TICKS_PER_SECOND

    get_headers = _auth_headers(token)
    post_headers = {**get_headers, "Content-Type": "application/json"}
    item_url = f"{url.rstrip('/')}/Users/{user_id}/Items/{item_id}"

    async def _do(c: httpx.AsyncClient) -> str:
        item_r = await c.get(item_url, headers=get_headers, params={"Fields": "UserData"})
        item_r.raise_for_status()
        item = item_r.json()
        user_data = item.get("UserData") or {}
        if user_data.get("Played"):
            return "skipped"
        current = int(user_data.get("PlaybackPositionTicks") or 0)
        if current >= ticks - POSITION_TOLERANCE_SECONDS * TICKS_PER_SECOND:
            return "skipped"
        runtime = int(item.get("RunTimeTicks") or 0)
        if runtime and ticks >= runtime:
            return "skipped"
        r = await c.post(f"{item_url}/UserData", headers=post_headers, json={**user_data, "PlaybackPositionTicks": ticks})
        return "pushed" if r.status_code < 400 else "failed"

    try:
        if client:
            return await _do(client)
        async with httpx.AsyncClient(timeout=PUSH_TIMEOUT, follow_redirects=False) as c:
            return await _do(c)
    except Exception:
        return "failed"
