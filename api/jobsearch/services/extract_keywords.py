"""Turns a resume into the search keywords used to query job boards."""

from pydantic import BaseModel

from jobsearch.config import get_settings
from jobsearch.services.llm import get_openai_client

_SYSTEM_PROMPT = (
    "You extract job-board search keywords from a resume. "
    "Return up to 10 short keywords (single technologies like 'react', 'python', "
    "or role titles like 'backend developer'), strongest match for the candidate first. "
    "Lowercase, no duplicates, no soft skills."
)


class ResumeKeywords(BaseModel):
    keywords: list[str]


async def extract_keywords(resume_text: str) -> list[str]:
    # chat.completions rather than the newer responses API so any
    # OpenAI-compatible provider (OpenRouter, Ollama, ...) works via base_url
    response = await get_openai_client().chat.completions.parse(
        model=get_settings().openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": resume_text},
        ],
        response_format=ResumeKeywords,
    )
    return response.choices[0].message.parsed.keywords[:10]
