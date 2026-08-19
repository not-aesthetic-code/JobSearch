"""Embedding calls. Same OpenAI-compatible client as the rest of the app, so
OpenRouter/Ollama endpoints work as long as they serve an embeddings model."""

from jobsearch.config import get_settings
from jobsearch.services.llm import get_openai_client

# text-embedding-3-small takes 8191 tokens; ~4 chars/token, so 8k chars is
# comfortably inside the limit and keeps the meaningful head of a posting
MAX_CHARS = 8000
BATCH_SIZE = 100


async def embed(texts: list[str]) -> list[list[float]]:
    """Embeddings for `texts`, same order. Batched so one call can't blow the
    per-request input limit."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = [text[:MAX_CHARS] or " " for text in texts[start : start + BATCH_SIZE]]
        response = await get_openai_client().embeddings.create(
            model=get_settings().embedding_model, input=batch
        )
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
    return vectors
