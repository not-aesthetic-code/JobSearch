from functools import lru_cache

from openai import AsyncOpenAI

from jobsearch.config import get_settings


@lru_cache(maxsize=1)
def get_openai_client() -> AsyncOpenAI:
    settings = get_settings()
    # `or None`: an empty OPENAI_BASE_URL= line in .env reads as "" — treat it as unset
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)
