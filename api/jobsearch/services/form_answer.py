"""Answers the application-form fields no keyword rule can: free-text questions,
dropdowns, radio groups, "why do you want to work here".

One LLM call per form, not per field — the model sees every unmatched field at
once, so an answer can reference the others ("notice period" vs "start date").
Each answer carries a confidence; the caller leaves the low ones blank for the
human rather than guessing on their behalf.
"""

from typing import Literal

from pydantic import BaseModel, Field

from jobsearch.config import get_settings
from jobsearch.services.llm import get_openai_client

FieldKind = Literal["text", "textarea", "select", "radio", "checkbox", "number", "date"]

_SYSTEM_PROMPT = (
    "You fill in job-application forms on behalf of one candidate. You are given "
    "their PROFILE (structured facts), their RESUME, the JOB POSTING, and the FIELDS "
    "of the form in front of you. Return one answer per field you can answer.\n"
    "Rules:\n"
    "- Every factual answer must come from PROFILE or RESUME. Never invent an "
    "employment date, salary figure, notice period, citizenship, visa or work-permit "
    "status, degree, certificate, security clearance, or any protected characteristic. "
    "If the fact is not in the inputs, set confidence to 0 and leave value empty.\n"
    "- For 'select' and 'radio' fields, value MUST be exactly one of the given options, "
    "copied character for character. If no option is supportable, confidence 0.\n"
    "- For free-text motivation questions, write in the candidate's own register: "
    "first person, concrete, 2-4 sentences, referencing real resume experience and the "
    "posting's actual stack. No superlatives, no invented enthusiasm about the company's "
    "history. Respect max_length.\n"
    "- Answer in the language the field label is written in.\n"
    "- confidence is how sure you are that the candidate themselves would send this "
    "exact answer: 1.0 for a fact copied straight out of PROFILE, ~0.7 for a well-"
    "grounded free-text answer, below 0.5 for anything you are inferring."
)


class FieldSpec(BaseModel):
    """One form control, as the model sees it."""

    index: int
    kind: FieldKind
    label: str
    options: list[str] = []
    required: bool = False
    max_length: int | None = None


class Answer(BaseModel):
    index: int
    value: str
    confidence: float = Field(ge=0, le=1)
    reason: str


class FormAnswers(BaseModel):
    answers: list[Answer]


def _render_fields(fields: list[FieldSpec]) -> str:
    lines = []
    for field in fields:
        parts = [f"[{field.index}] ({field.kind})", field.label or "<no label>"]
        if field.required:
            parts.append("REQUIRED")
        if field.max_length:
            parts.append(f"max {field.max_length} chars")
        if field.options:
            parts.append("options: " + " | ".join(field.options))
        lines.append(" — ".join(parts))
    return "\n".join(lines)


async def answer_fields(
    fields: list[FieldSpec], profile: dict, resume_text: str, job_text: str
) -> dict[int, Answer]:
    """Answers keyed by field index. Fields the model skipped are simply absent."""
    if not fields:
        return {}
    profile_text = "\n".join(f"{key}: {value}" for key, value in profile.items() if value)
    response = await get_openai_client().chat.completions.parse(
        model=get_settings().openai_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"PROFILE:\n{profile_text}\n\n"
                    f"RESUME:\n{resume_text}\n\n"
                    f"JOB POSTING:\n{job_text}\n\n"
                    f"FIELDS:\n{_render_fields(fields)}"
                ),
            },
        ],
        response_format=FormAnswers,
    )
    parsed = response.choices[0].message.parsed
    return {answer.index: answer for answer in parsed.answers if answer.value.strip()}
