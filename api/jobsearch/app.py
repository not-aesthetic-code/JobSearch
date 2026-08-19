from fastapi import FastAPI

from jobsearch.config import get_settings
from jobsearch.endpoints.pipeline import router as pipeline_router
from jobsearch.endpoints.profile import router as profile_router
from jobsearch.endpoints.status import router as status_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.include_router(status_router)
    app.include_router(profile_router)
    app.include_router(pipeline_router)
    return app


app = create_app()
