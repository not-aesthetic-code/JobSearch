import asyncio
import subprocess
import sys
import uuid
from pathlib import Path
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.auth import RequireServiceKey
from jobsearch.config import get_settings
from jobsearch.database.models import MatchJob
from jobsearch.database.session import get_session, get_sessionmaker
from jobsearch.services.match import MatchMark, SortKey, count_shortlist, get_shortlist, mark_match
from jobsearch.services.pipeline import PHASES, SOURCES, get_latest_resume, get_or_create_local_user, run_pipeline

router = APIRouter(dependencies=[RequireServiceKey])

# ponytail: in-process state — fine for the single-worker personal deployment,
# move to a DB row if this ever runs multi-worker
_running = False
_last_error: str | None = None
_phase: str | None = None
_progress: dict[str, object] | None = None
_task: asyncio.Task | None = None

APPLY_LOG = "/tmp/jobsearch-apply.log"

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class RunPipelineRequest(BaseModel):
    # omit it to run against whatever the profile has stored
    resume_text: str | None = Field(default=None, min_length=50, description="Plain-text resume")
    # omit it to ingest from every source; [] skips ingest and just re-retrieves/re-scores
    # what's already stored
    sources: list[str] | None = Field(default=None, description=f"subset of {SOURCES}")


class ShortlistItem(BaseModel):
    id: uuid.UUID
    seen: bool
    applied: bool
    score: int
    summary: str
    title: str
    company: str | None
    url: str
    remote: bool | None  # None = the source never said
    location: str | None
    posted_at: datetime | None
    seniority: str | None  # junior | mid | senior; None = scored before we tracked it


class ShortlistPage(BaseModel):
    items: list[ShortlistItem]
    total: int


def _set_phase(name: str) -> None:
    global _phase, _progress
    _phase = name
    _progress = None  # a new phase starts with no sub-progress yet


def _set_progress(source: str, done: int, total: int) -> None:
    global _progress
    _progress = {"source": source, "done": done, "total": total}


async def _run_in_background(resume_text: str, sources: set[str] | None) -> None:
    global _running, _last_error
    try:
        async with get_sessionmaker()() as session:
            await run_pipeline(
                session, resume_text, on_phase=_set_phase, on_progress=_set_progress, sources=sources
            )
        _last_error = None
    except asyncio.CancelledError:
        _last_error = "Stopped"
    except Exception as exc:  # noqa: BLE001 — surface via /pipeline/status, don't kill the worker
        _last_error = f"{type(exc).__name__}: {exc}"
    finally:
        _running = False


@router.post("/pipeline/run", status_code=status.HTTP_202_ACCEPTED, tags=["Pipeline"])
async def start_pipeline(request: RunPipelineRequest, session: SessionDep) -> dict[str, str]:
    global _running, _phase, _progress, _task
    if not get_settings().openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OPENAI_API_KEY is not configured on the API server (api/.env)",
        )
    if _running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A pipeline run is already in progress")
    if request.sources is not None and (unknown := set(request.sources) - set(SOURCES)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unknown source(s): {sorted(unknown)}")

    resume_text = request.resume_text
    if resume_text is None:
        user = await get_or_create_local_user(session)
        resume = await get_latest_resume(session, user.id)
        if resume is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No resume saved yet — add one on the profile page first",
            )
        resume_text = resume.raw_text

    _running = True
    _phase = PHASES[0]
    _progress = None
    sources = set(request.sources) if request.sources is not None else None
    _task = asyncio.create_task(_run_in_background(resume_text, sources))
    return {"status": "started"}


@router.post("/pipeline/stop", tags=["Pipeline"])
async def stop_pipeline() -> dict[str, str]:
    if not _running or _task is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No pipeline run in progress")
    _task.cancel()
    return {"status": "stopping"}


@router.get("/pipeline/status", tags=["Pipeline"])
async def pipeline_status(session: SessionDep) -> dict[str, object]:
    counts = dict(
        (await session.execute(select(MatchJob.status, func.count()).group_by(MatchJob.status))).all()
    )
    return {
        "running": _running,
        "phase": _phase,
        "phases": PHASES,
        "progress": _progress,
        "sources": SOURCES,
        "jobs": counts,
        "last_error": _last_error,
    }


@router.get("/shortlist", tags=["Pipeline"])
async def shortlist(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: SortKey = "score",
    remote: Annotated[bool | None, Query(description="omit for any; true/false filters out unknowns")] = None,
    min_score: Annotated[
        int | None, Query(ge=0, le=100, description="omit for the configured match threshold")
    ] = None,
    junior: Annotated[bool, Query(description="include junior-level postings (hidden by default)")] = False,
) -> ShortlistPage:
    user = await get_or_create_local_user(session)
    rows = await get_shortlist(session, user.id, min_score=min_score, limit=limit, offset=offset, sort=sort, remote=remote, junior=junior)
    return ShortlistPage(
        items=[
            ShortlistItem(
                id=match_id,
                seen=seen_at is not None,
                applied=applied_at is not None,
                score=score,
                summary=summary,
                title=title,
                company=company,
                url=url,
                remote=is_remote,
                location=location,
                posted_at=posted_at,
                seniority=seniority,
            )
            for score, summary, title, company, url, is_remote, location, posted_at, match_id, seen_at, applied_at, seniority in rows
        ],
        total=await count_shortlist(session, user.id, min_score=min_score, remote=remote, junior=junior),
    )


@router.post("/shortlist/{match_id}/apply", status_code=status.HTTP_202_ACCEPTED, tags=["Pipeline"])
async def start_apply(match_id: uuid.UUID) -> dict[str, str]:
    """Opens a visible browser on the machine the API runs on, fills the form and
    stops before Submit (ADR 0003). Only meaningful when the API runs on your desktop."""
    # ponytail: fire-and-forget subprocess; the window is the UI. Mark "applied" is a manual click.
    if not Path("profile.json").exists():  # the CLI would exit instantly and the 202 would be a lie
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="api/profile.json is missing — create it first (see cli/apply.py)")
    log = open(APPLY_LOG, "w")  # a silent failure (no profile.json, no browser) is otherwise invisible
    subprocess.Popen(
        [sys.executable, "-m", "cli.apply", "--match-id", str(match_id)],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
    )
    return {"status": "started"}


@router.post("/shortlist/{match_id}/{mark}", status_code=status.HTTP_204_NO_CONTENT, tags=["Pipeline"])
async def mark_shortlist_item(match_id: uuid.UUID, mark: MatchMark, session: SessionDep) -> None:
    user = await get_or_create_local_user(session)
    if not await mark_match(session, user.id, match_id, mark):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such match")
