"""Managed profiles: password-less Scrob accounts owned by one login.

A household owner keeps a single login and manages a profile per person. Each
profile is an ordinary Scrob user underneath (its own history, ratings,
progress, connections and API key), so nothing else in Scrob needs to know
about profiles. A profile has no password and can't be logged into directly;
only its owner can switch into it, and a managed profile can't manage others.
"""
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core import emby
from core.household import is_active, summarise_jobs
from core.profile_names import same_server, unique_username
from core.security import create_access_token, session_lifetime
from core.timeutil import utcnow
from db import get_db
from dependencies import get_current_user
from models.base import UserRole
from models.connections import MediaServerConnection
from models.sync import SyncJob, SyncStatus
from models.users import User, UserSettings

logger = logging.getLogger("uvicorn.error")
router = APIRouter()

MAX_IMPORT_PEOPLE = 50


def _require_owner(user: User) -> None:
    """Only a normal (non-managed) account may manage profiles."""
    if user.managed_by_user_id is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Switch back to your own account to manage profiles")


async def _get_managed(db: AsyncSession, owner: User, profile_id: int) -> User:
    result = await db.execute(
        select(User).where(User.id == profile_id, User.managed_by_user_id == owner.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return profile


async def _create_profile(db: AsyncSession, owner: User, name: str) -> User:
    name = " ".join((name or "").split())
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A profile needs a name")
    name = name[:60]
    taken = {
        row.lower()
        for row in (await db.execute(
            select(User.username).where(func.lower(User.username).startswith(name.lower(), autoescape=True))
        )).scalars().all()
    }
    profile = User(
        # Never delivered to: .invalid is reserved, and the profile has no password to reset.
        email=f"managed-{secrets.token_hex(8)}@profiles.invalid",
        username=unique_username(name, taken),
        password_hash=None,
        api_key=secrets.token_urlsafe(32),
        role=UserRole.user,
        is_admin=False,
        email_confirmed=True,
        managed_by_user_id=owner.id,
    )
    db.add(profile)
    await db.flush()

    # A personal TMDB key would otherwise leave the profile unable to look up media.
    owner_settings = (await db.execute(select(UserSettings).where(UserSettings.user_id == owner.id))).scalar_one_or_none()
    if owner_settings is not None and owner_settings.tmdb_api_key:
        db.add(UserSettings(user_id=profile.id, tmdb_api_key=owner_settings.tmdb_api_key))
    return profile


_same_server = same_server


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ImportPerson(BaseModel):
    emby_user_id: str = Field(min_length=1, max_length=255)
    emby_username: str = Field(default="", max_length=255)
    # Either an existing profile (or the owner's own id) ...
    profile_id: Optional[int] = None
    # ... or the name of a new profile to create.
    new_profile_name: Optional[str] = Field(default=None, max_length=60)


class ImportBody(BaseModel):
    connection_id: int
    people: list[ImportPerson] = Field(max_length=MAX_IMPORT_PEOPLE)


async def _profile_payload(db: AsyncSession, profiles: list[User]) -> list[dict]:
    ids = [p.id for p in profiles]
    conns_by_user: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        rows = (await db.execute(
            select(MediaServerConnection).where(MediaServerConnection.user_id.in_(ids)).order_by(MediaServerConnection.id)
        )).scalars().all()
        for c in rows:
            conns_by_user[c.user_id].append(
                {"id": c.id, "name": c.name, "type": c.type, "server_username": c.server_username}
            )
    return [
        {"id": p.id, "username": p.username, "api_key": p.api_key, "connections": conns_by_user[p.id]}
        for p in profiles
    ]


@router.get("")
async def list_profiles(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The signed-in account and, for an owner, the profiles they manage."""
    if current_user.managed_by_user_id is not None:
        return {"managed": True, "owner_id": current_user.managed_by_user_id, "username": current_user.username, "profiles": []}
    profiles = (await db.execute(
        select(User).where(User.managed_by_user_id == current_user.id).order_by(User.id)
    )).scalars().all()
    return {
        "managed": False,
        "owner_id": current_user.id,
        "owner_api_key": current_user.api_key,
        "username": current_user.username,
        "profiles": await _profile_payload(db, list(profiles)),
    }


async def _household_people(db: AsyncSession, owner: User) -> list[User]:
    """The owner first, then every managed profile in creation order."""
    managed = (await db.execute(
        select(User).where(User.managed_by_user_id == owner.id).order_by(User.id)
    )).scalars().all()
    return [owner, *managed]


@router.get("/overview")
async def household_overview(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Everyone in the household with their server connections and what each pull/push is doing."""
    _require_owner(current_user)
    people = await _household_people(db, current_user)
    conns = (await db.execute(
        select(MediaServerConnection)
        .where(MediaServerConnection.user_id.in_([p.id for p in people]))
        .order_by(MediaServerConnection.id)
    )).scalars().all()
    jobs = []
    if conns:
        jobs = (await db.execute(
            select(SyncJob)
            .where(SyncJob.connection_id.in_([c.id for c in conns]))
            .order_by(SyncJob.created_at.desc(), SyncJob.id.desc())
            .limit(2000)
        )).scalars().all()
    summary = summarise_jobs(jobs, utcnow())

    by_user: dict[int, list[dict]] = {p.id: [] for p in people}
    for c in conns:
        job_info = summary.get(c.id, {})
        by_user[c.user_id].append({
            "id": c.id,
            "name": c.name,
            "type": c.type,
            "url": c.url,
            "server_username": c.server_username,
            "push_enabled": c.push_enabled,
            "sync_collection": c.sync_collection,
            "pull": job_info.get("pull"),
            "push": job_info.get("push"),
        })
    return {
        "owner_id": current_user.id,
        "owner_api_key": current_user.api_key,
        "people": [
            {
                "id": p.id,
                "username": p.username,
                "is_owner": p.id == current_user.id,
                "api_key": p.api_key,
                "connections": by_user[p.id],
            }
            for p in people
        ],
    }


async def _household_connection(db: AsyncSession, owner: User, connection_id: int) -> tuple[MediaServerConnection, User]:
    """A connection of the owner or of one of their profiles, with the user it belongs to."""
    conn = (await db.execute(
        select(MediaServerConnection).where(MediaServerConnection.id == connection_id)
    )).scalar_one_or_none()
    if conn is not None and conn.user_id == owner.id:
        return conn, owner
    if conn is not None:
        target = (await db.execute(
            select(User).where(User.id == conn.user_id, User.managed_by_user_id == owner.id)
        )).scalar_one_or_none()
        if target is not None:
            return conn, target
    # Same answer for "doesn't exist" and "someone else's", so ids can't be probed.
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")


async def _has_active_job(db: AsyncSession, connection_id: int, job_type: str) -> bool:
    job = (await db.execute(
        select(SyncJob)
        .where(
            SyncJob.connection_id == connection_id,
            SyncJob.job_type == job_type,
            SyncJob.status.in_([SyncStatus.pending, SyncStatus.running]),
        )
        .order_by(SyncJob.created_at.desc(), SyncJob.id.desc())
        .limit(1)
    )).scalar_one_or_none()
    return job is not None and is_active(job.status, job.updated_at, utcnow())


async def _start_job(
    db: AsyncSession, background_tasks: BackgroundTasks, kind: str, conn: MediaServerConnection, target: User
) -> dict:
    """Start a pull or push for one connection exactly as its own owner would from the Connections page.

    Skips (rather than doubling up) when one is already queued or running. Jobs
    started in one request run one after the other: they share the request's
    background queue, and Scrob only ever runs one sync at a time anyway.
    """
    from routers import sync as sync_router  # imported here: sync.py is large and imports a lot

    if await _has_active_job(db, conn.id, kind):
        return {"connection_id": conn.id, "status": "already running"}
    try:
        if kind == "pull":
            result = await sync_router.sync_connection(
                conn.id, background_tasks, movie_limit=0, show_limit=0, full=False, db=db, current_user=target,
            )
        else:
            result = await sync_router.push_upstream(conn.id, background_tasks, db=db, current_user=target)
    except HTTPException as exc:
        return {"connection_id": conn.id, "status": "error", "detail": str(exc.detail)}
    return {"connection_id": conn.id, "status": "started", "job_id": result.get("job_id")}


async def _start_one(
    kind: str, connection_id: int, background_tasks: BackgroundTasks, db: AsyncSession, owner: User
) -> dict:
    _require_owner(owner)
    conn, target = await _household_connection(db, owner, connection_id)
    result = await _start_job(db, background_tasks, kind, conn, target)
    if result["status"] == "error":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("detail") or "Couldn't start")
    return result


@router.post("/connections/{connection_id}/pull")
async def pull_connection(
    connection_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pull one of the household's connections (the owner's or a profile's)."""
    return await _start_one("pull", connection_id, background_tasks, db, current_user)


@router.post("/connections/{connection_id}/push")
async def push_connection(
    connection_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Push to one of the household's connections (the owner's or a profile's)."""
    return await _start_one("push", connection_id, background_tasks, db, current_user)


async def _start_all(kind: str, background_tasks: BackgroundTasks, db: AsyncSession, owner: User) -> dict:
    _require_owner(owner)
    people = await _household_people(db, owner)
    conns = (await db.execute(
        select(MediaServerConnection)
        .where(MediaServerConnection.user_id.in_([p.id for p in people]))
        .order_by(MediaServerConnection.id)
    )).scalars().all()
    people_by_id = {p.id: p for p in people}
    order = {p.id: i for i, p in enumerate(people)}
    results = []
    for conn in sorted(conns, key=lambda c: (order[c.user_id], c.id)):
        if kind == "push" and not conn.push_enabled:
            continue
        results.append(await _start_job(db, background_tasks, kind, conn, people_by_id[conn.user_id]))
    return {"results": results, "started": sum(1 for r in results if r["status"] == "started")}


@router.post("/pull-all")
async def pull_all(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue a pull for every connection in the household, one after another (you first)."""
    return await _start_all("pull", background_tasks, db, current_user)


@router.post("/push-all")
async def push_all(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Queue a push for every connection that has pushing switched on, one after another."""
    return await _start_all("push", background_tasks, db, current_user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: ProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_owner(current_user)
    profile = await _create_profile(db, current_user, body.name)
    await db.commit()
    logger.info("User %s created managed profile %s", current_user.id, profile.id)
    return (await _profile_payload(db, [profile]))[0]


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently deletes a profile and ALL of its data (history, ratings, connections)."""
    _require_owner(current_user)
    profile = await _get_managed(db, current_user, profile_id)
    await db.delete(profile)
    await db.commit()
    logger.info("User %s deleted managed profile %s", current_user.id, profile_id)
    return {"status": "deleted"}


@router.post("/{profile_id}/switch")
async def switch_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """A login token for one of the caller's own managed profiles."""
    _require_owner(current_user)
    profile = await _get_managed(db, current_user, profile_id)
    lifetime = session_lifetime(False)
    logger.info("User %s switched into managed profile %s", current_user.id, profile.id)
    return {
        "access_token": create_access_token(subject=profile.id, expires_delta=lifetime),
        "expires_in": int(lifetime.total_seconds()),
        "username": profile.username,
    }


async def _owned_server_connection(db: AsyncSession, owner: User, connection_id: int) -> MediaServerConnection:
    conn = (await db.execute(
        select(MediaServerConnection).where(
            MediaServerConnection.id == connection_id,
            MediaServerConnection.user_id == owner.id,
        )
    )).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    if conn.type not in ("emby", "jellyfin"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only Emby and Jellyfin connections can list users")
    return conn


@router.get("/server-users")
async def server_users(
    connection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The users on one of the owner's Emby/Jellyfin servers, and which profile each is linked to."""
    _require_owner(current_user)
    conn = await _owned_server_connection(db, current_user, connection_id)
    users = await emby.list_users(conn.url, conn.token)
    if users is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Couldn't read the user list from the server (the connection's API key must be an administrator key)",
        )

    owned_ids = [current_user.id] + list((await db.execute(
        select(User.id).where(User.managed_by_user_id == current_user.id)
    )).scalars().all())
    linked: dict[str, int] = {}
    for c in (await db.execute(
        select(MediaServerConnection).where(
            MediaServerConnection.user_id.in_(owned_ids),
            MediaServerConnection.type == conn.type,
        )
    )).scalars().all():
        if c.server_user_id and _same_server(c.url, conn.url):
            linked[c.server_user_id] = c.user_id
    return [{**u, "linked_profile_id": linked.get(u["id"])} for u in users]


@router.post("/import-server-users")
async def import_server_users(
    body: ImportBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Link server users to profiles (creating profiles as asked) by adding a connection per person.

    Each new connection copies the source connection's server URL, API key and
    sync/push settings; only the server user differs. Nothing is synced until
    you switch into the profile and run a Pull.
    """
    _require_owner(current_user)
    src = await _owned_server_connection(db, current_user, body.connection_id)

    results = []
    for person in body.people:
        if person.profile_id is not None and person.profile_id != current_user.id:
            target = await _get_managed(db, current_user, person.profile_id)
        elif person.profile_id == current_user.id:
            target = current_user
        elif person.new_profile_name and person.new_profile_name.strip():
            target = await _create_profile(db, current_user, person.new_profile_name)
        else:
            results.append({"emby_user_id": person.emby_user_id, "status": "skipped"})
            continue

        existing = (await db.execute(
            select(MediaServerConnection).where(
                MediaServerConnection.user_id == target.id,
                MediaServerConnection.type == src.type,
                MediaServerConnection.server_user_id == person.emby_user_id,
            )
        )).scalars().all()
        if any(_same_server(c.url, src.url) for c in existing):
            results.append({"emby_user_id": person.emby_user_id, "profile_id": target.id, "status": "already linked"})
            continue

        db.add(MediaServerConnection(
            user_id=target.id,
            type=src.type,
            name=src.name,
            url=src.url,
            token=src.token,
            server_user_id=person.emby_user_id,
            server_username=person.emby_username or None,
            sync_collection=src.sync_collection,
            sync_watched=src.sync_watched,
            sync_ratings=src.sync_ratings,
            sync_playback=src.sync_playback,
            push_watched=src.push_watched,
            push_playback=src.push_playback,
            push_ratings=src.push_ratings,
            auto_sync_interval=src.auto_sync_interval,
            auto_push_interval=src.auto_push_interval,
        ))
        results.append({"emby_user_id": person.emby_user_id, "profile_id": target.id, "status": "linked"})
    await db.commit()
    return {"results": results}
