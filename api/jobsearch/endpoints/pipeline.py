import asyncio
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
from jobsearch.services.match import SortKey, count_shortlist, get_shortlist
from jobsearch.services.pipeline import PHASES, SOURCES, get_latest_resume, get_or_create_local_user, run_pipeline

router = APIRouter(dependencies=[RequireServiceKey])

# ponytail: in-process state — fine for the single-worker personal deployment,
# move to a DB row if this ever runs multi-worker
_running = False
_last_error: str | None = None
_phase: str | None = None
_progress: dict[str, object] | None = None
_task: asyncio.Task | None = None

SessionDep = Annotated[AsyncSession, Depends(get_session)]


class RunPipelineRequest(BaseModel):
    # omit it to run against whatever the profile has stored
    resume_text: str | None = Field(default=None, min_length=50, description="Plain-text resume")
    # omit it to ingest from every source; [] skips ingest and just re-retrieves/re-scores
    # what's already stored
    sources: list[str] | None = Field(default=None, description=f"subset of {SOURCES}")


class ShortlistItem(BaseModel):
    score: int
    summary: str
    title: str
    company: str | None
    url: str
    remote: bool | None  # None = the source never said
    location: str | None
    posted_at: datetime | None


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
) -> ShortlistPage:
    user = await get_or_create_local_user(session)
    rows = await get_shortlist(session, user.id, min_score=min_score, limit=limit, offset=offset, sort=sort, remote=remote)
    return ShortlistPage(
        items=[
            ShortlistItem(
                score=score,
                summary=summary,
                title=title,
                company=company,
                url=url,
                remote=is_remote,
                location=location,
                posted_at=posted_at,
            )
            for score, summary, title, company, url, is_remote, location, posted_at in rows
        ],
        total=await count_shortlist(session, user.id, min_score=min_score, remote=remote),
    )
