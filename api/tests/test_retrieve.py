"""RRF fusion, with both retrieval channels stubbed — no DB, no embedding calls.
The fusion arithmetic is the only part of retrieval that can be wrong quietly:
a bad SQL clause raises, a bad ranking just returns mediocre jobs forever."""

import uuid

from jobsearch.services import retrieve as retrieve_module
from jobsearch.services.retrieve import retrieve

A, B, C, D = (uuid.UUID(int=n) for n in range(1, 5))


def _stub_channels(monkeypatch, dense: list[uuid.UUID], lexical: list[uuid.UUID]) -> None:
    async def fake_embed(texts):
        return [[0.0] for _ in texts]

    async def fake_dense(session, query_vector, top_k):
        return dense[:top_k]

    async def fake_lexical(session, query, top_k):
        return lexical[:top_k]

    monkeypatch.setattr(retrieve_module, "embed", fake_embed)
    monkeypatch.setattr(retrieve_module, "_dense_ranking", fake_dense)
    monkeypatch.setattr(retrieve_module, "_lexical_ranking", fake_lexical)


async def test_posting_found_by_both_channels_outranks_either_channels_top_hit(monkeypatch):
    # B is 2nd in both channels; A and C top one channel each and are absent from the other
    _stub_channels(monkeypatch, dense=[A, B], lexical=[C, B])

    assert await retrieve(None, ["python"], top_k=10) == [B, A, C]


async def test_ranks_fuse_across_queries(monkeypatch):
    # same rankings for every query, so the order is just the dense/lexical order
    _stub_channels(monkeypatch, dense=[A, B, C], lexical=[A, B, C])

    assert await retrieve(None, ["python", "fastapi"], top_k=10) == [A, B, C]


async def test_respects_top_k_as_both_per_channel_and_final_limit(monkeypatch):
    _stub_channels(monkeypatch, dense=[A, B, C, D], lexical=[D, C, B, A])

    result = await retrieve(None, ["python"], top_k=2)

    assert len(result) == 2
    assert set(result) == {A, D}  # rank-1 hits of each channel; B and C never returned


async def test_no_queries_retrieves_nothing(monkeypatch):
    _stub_channels(monkeypatch, dense=[A], lexical=[A])

    assert await retrieve(None, [], top_k=10) == []
