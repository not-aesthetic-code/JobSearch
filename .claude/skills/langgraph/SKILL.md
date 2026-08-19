---
name: langgraph
description: Fetch current LangGraph / LangChain docs before writing or reviewing LangGraph code. Use whenever the task involves StateGraph, nodes/edges, reducers, subgraphs, checkpointers/persistence, stores/memory, interrupts and human-in-the-loop, streaming, the Functional API (@entrypoint/@task), langgraph CLI or Studio, or LangGraph Platform deploys. Triggers on "langgraph", "state graph", "checkpointer", "interrupt", "human in the loop", "agent graph", "@entrypoint", "langgraph dev", or any langgraph/langchain import.
---

# LangGraph

Model memory of LangGraph is stale — the API churns. Fetch docs first, then write code.

## Get the docs

```
mcp__context7__resolve-library-id: "langgraph"   # → e.g. /websites/langchain_docs
mcp__context7__query-docs: libraryId + a specific question
```

Ask one narrow question per call ("how do I resume from an interrupt", not "langgraph"). Fall back to WebFetch on `https://docs.langchain.com/oss/python/langgraph/<page>` (`use-graph-api`, `persistence`, `interrupts`, `streaming`, `use-subgraphs`, `use-functional-api`, `add-memory`, `test`).

## Facts worth double-checking against the docs (common stale-model mistakes)

- Streaming: `graph.stream_events(input, version="v3")`. `.output` drives the stream to completion, `.interrupts` holds pending interrupts.
- Messages import from `langchain.messages` (`AnyMessage`, `SystemMessage`, `ToolMessage`), models via `langchain.chat_models.init_chat_model`.
- Human-in-the-loop: `interrupt(payload)` inside a node, resume with `graph.stream_events(Command(resume=...), config=...)`. Requires a checkpointer + `thread_id`.
- A node re-runs from the top on resume — side effects before `interrupt()` happen twice.
- Subgraph state keys are only shared with the parent when the schemas share the key name; otherwise transform in/out yourself.
- Postgres/Redis/Oracle checkpointers need `.setup()` once and their own package (`langgraph-checkpoint-postgres`, etc.).

## This repo

`api/` is Python 3.13 + uv. Add deps with `uv add langgraph`, not pip.

ponytail: no vendored doc copies — context7 serves live docs; this file only holds what a model gets wrong from memory.
