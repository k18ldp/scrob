"""Helpers for the household overview: what each connection's pull/push is doing."""
from datetime import datetime, timedelta

ACTIVE_STATUSES = frozenset({"pending", "running"})
# A job still "pending/running" after this long is treated as dead (e.g. the container
# restarted mid-sync) so it can't block a new pull forever.
STALE_AFTER = timedelta(hours=3)


def _status(job) -> str:
    status = getattr(job, "status", None)
    return str(getattr(status, "value", status) or "")


def is_active(status, updated_at: datetime | None, now: datetime) -> bool:
    """True while a job is queued or running and has shown signs of life recently."""
    value = str(getattr(status, "value", status) or "")
    if value not in ACTIVE_STATUSES:
        return False
    if updated_at is None:
        return True
    return now - updated_at < STALE_AFTER


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def job_summary(job, now: datetime) -> dict:
    return {
        "id": job.id,
        "status": _status(job),
        "active": is_active(job.status, job.updated_at, now),
        "step": job.current_step,
        "processed": job.processed_items or 0,
        "total": job.total_items or 0,
        "error": (job.error_message or None),
        "updated_at": _iso(job.updated_at),
    }


def summarise_jobs(jobs_newest_first, now: datetime) -> dict[int, dict]:
    """``{connection_id: {"pull": {...}, "push": {...}}}`` from jobs ordered newest first.

    Each of pull/push holds the newest job (``latest``) and when the newest *completed*
    one finished (``last_ok_at``). Jobs without a connection, or of another kind, are ignored.
    """
    out: dict[int, dict] = {}
    for job in jobs_newest_first:
        if job.connection_id is None or job.job_type not in ("pull", "push"):
            continue
        slot = out.setdefault(job.connection_id, {}).setdefault(
            job.job_type, {"latest": None, "last_ok_at": None}
        )
        if slot["latest"] is None:
            slot["latest"] = job_summary(job, now)
        if slot["last_ok_at"] is None and _status(job) == "completed":
            slot["last_ok_at"] = _iso(job.updated_at)
    return out
