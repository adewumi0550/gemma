# PRD — Gemma Agentic AI on Cloud Run

**Owner:** adewumi0550
**Status:** Draft for review
**Date:** 2026-08-04
**Purpose:** Reference implementation + live demo of an open-model agent built on **Google ADK**, with tools exposed over **MCP**, running on **Gemma**, tested locally and deployed to **Cloud Run**.

---

## 1. Background

Most agent demos are a thin wrapper around a hosted frontier model. This project demonstrates the opposite, and the more interesting engineering story:

- an **open-weights model** (Gemma) you run yourself,
- driven by a **real agent framework** (ADK) rather than a hand-rolled while-loop,
- calling tools through an **open protocol** (MCP) rather than hardcoded Python functions,
- with **identical code** running on a laptop and on Cloud Run.

The portability claim is the thesis of the talk. Everything in this PRD serves it.

### 1.1 ADK vs MCP — the framing this project depends on

These are frequently presented as competing choices. They are not. They occupy different layers:

| | **ADK** (Agent Development Kit) | **MCP** (Model Context Protocol) |
|---|---|---|
| What it is | Agent framework / runtime | Client–server protocol for tools & context |
| Solves | Orchestration, sessions, state, streaming, eval, deploy | How an agent *discovers and calls* tools it doesn't own |
| Analogy | The web framework | HTTP |
| Scope | One agent application | Any agent, any vendor |

ADK ships an `MCPToolset` that connects to MCP servers and surfaces their tools to the agent. So the composition is:

```
Gemma (model)  ←  ADK (agent runtime)  ←  MCPToolset  ←  MCP server(s) (tools)
```

**Decision: build both layers.** Tools live behind an MCP server; the agent is an ADK agent that consumes them. This gives the demo two independently reusable artifacts — an MCP server any agent can use, and an ADK agent any model can drive.

---

## 2. Goals & non-goals

### Goals

| # | Goal | Success measure |
|---|---|---|
| G1 | Working agentic loop on Gemma — multi-step reasoning, tool selection, tool execution, synthesis | Agent completes a ≥3-tool-call task unaided |
| G2 | Tools served over MCP, not hardcoded | Tools resolve via `MCPToolset`; server runs standalone against any MCP client |
| G3 | Runs fully local, zero cloud dependency, zero API keys | `make dev` works with network disabled (except tool-specific egress) |
| G4 | Same image deploys to Cloud Run | One `deploy.sh`; no source changes between local and cloud |
| G5 | Presentable | `adk web` UI shows the reasoning trace live; p95 latency acceptable on stage |

### Non-goals

- Fine-tuning or training Gemma.
- Production auth, multi-tenancy, rate limiting, or quota management.
- Beating a frontier model on quality. The point is architecture, not benchmark position.
- Multi-agent orchestration. Single agent; note ADK's multi-agent support as future work.

---

## 3. Users

| Persona | Need | What they take away |
|---|---|---|
| **Presentation audience** (primary) | Understand agents concretely, not abstractly | "Open model + ADK + MCP is a real stack, and it deploys" |
| **Developer cloning the repo** | A runnable starting point | `git clone && make dev` works in <10 min |
| **You, on stage** | Nothing fails live | Deterministic demo path, offline fallback, pre-warmed instance |

---

## 4. Verified environment

Confirmed on this machine, 2026-08-04:

| Component | Version / value | Note |
|---|---|---|
| Model | `gemma4:latest` | 8.0B, Q4_K_M, **131,072** ctx, 9.6 GB |
| Capabilities | `completion, tools, thinking, vision, audio` | **Native tool-calling supported** — no prompt-hack fallback needed as primary path |
| Runtime | Ollama 0.32.5 | Serving on `localhost:11434`, model already pulled |
| Python | 3.14.3 | |
| Package manager | uv 0.11.21 | |
| Docker | 29.6.1 | |
| gcloud | 559.0.0 | project set, region `us-central1` |
| Local GPU | none (Apple Silicon, Metal) | Ollama uses Metal; fine for 8B Q4 |

`tools` + `thinking` in the capability list is the enabling fact for this project — Gemma 4 can drive a real function-calling loop, and the thinking trace is excellent presentation material.

---

## 5. Architecture

### 5.1 Local

```
┌──────────────┐   HTTP    ┌───────────────────────┐  stdio/MCP  ┌────────────────┐
│  adk web UI  │ ────────► │  ADK agent (FastAPI)  │ ──────────► │  MCP tool srv  │
│  or curl     │           │  LiteLlm → ollama     │             │  (FastMCP)     │
└──────────────┘           └───────────┬───────────┘             └───────┬────────┘
                                       │ :11434                          │
                                  ┌────▼─────┐                    ┌──────▼───────┐
                                  │  Ollama  │                    │ public APIs  │
                                  │  gemma4  │                    │ (no API key) │
                                  └──────────┘                    └──────────────┘
```

### 5.2 Cloud Run

Two services, so the model scales independently of the agent and the agent stays cheap:

```
      ┌────────────────────────────┐            ┌──────────────────────────────┐
─────►│  gemma-agent  (CPU)        │───────────►│  gemma-model  (GPU: 1× L4)   │
      │  ADK + MCP server in-proc  │  OpenAI-   │  Ollama + gemma4 baked in    │
      │  min-instances 1           │  compatible│  min-instances 1 (demo day)  │
      └────────────────────────────┘            └──────────────────────────────┘
```

**Why split:** the agent container is ~200 MB and starts in seconds; the model container is ~10 GB and needs a GPU. Coupling them means every agent redeploy re-pushes 10 GB and every scale event pays a GPU cold start.

**Model access — decision required (§9, D1):**

| Option | Cost | Cold start | Story |
|---|---|---|---|
| **A. Self-host** Gemma on Cloud Run GPU (L4) | GPU-hour | 20–60s (baked image) | "We own the whole stack" — strongest for an open-model talk |
| **B. Managed** Gemma via Vertex AI / AI Studio | per-token | ~0 | Simplest, safest on stage |

**Recommendation: build A, keep B configured as a one-env-var fallback.** `MODEL_BACKEND=selfhosted|vertex` selects at runtime. If GPU quota or cold start misbehaves on demo day, you flip a variable instead of debugging live.

### 5.3 Portability mechanism

The agent never imports Ollama. It talks to one OpenAI-compatible base URL:

```
LLM_BASE_URL=http://localhost:11434/v1        # local
LLM_BASE_URL=https://gemma-model-….run.app/v1 # Cloud Run
```

That single variable *is* G4. It should be an explicit beat in the talk.

---

## 6. Functional requirements

### 6.1 MCP tool server

Tools chosen so the demo needs **no API keys** — a hard requirement, since key provisioning is the most common live-demo failure.

| ID | Tool | Source | Why it's in the demo |
|---|---|---|---|
| T1 | `calculator` | local, safe AST eval | Proves the model defers instead of hallucinating arithmetic |
| T2 | `search_wikipedia` | Wikipedia REST, keyless | External knowledge retrieval |
| T3 | `get_weather` | Open-Meteo, keyless | Multi-step: geocode → forecast (two chained calls) |
| T4 | `current_time` | local | Trivial; proves grounding in the present |

- **FR-1** Server implements MCP over stdio (local) and HTTP/SSE (cloud).
- **FR-2** Every tool has a typed signature and a docstring — Gemma selects tools from these descriptions, so docstring quality is a functional requirement, not documentation.
- **FR-3** Tool failure returns a structured error the agent can reason about and retry; it never raises into the agent loop.
- **FR-4** Server is independently runnable and testable against any MCP client.

### 6.2 ADK agent

- **FR-5** `LlmAgent` with Gemma via `LiteLlm`, tools loaded through `MCPToolset`.
- **FR-6** Multi-turn tool calling to a bounded step limit (default 8) with a clear terminal state.
- **FR-7** Session state persists across turns within a conversation.
- **FR-8** Streams tokens and emits tool-call events — the audience must *see* the agent decide.
- **FR-9** `thinking` output captured and surfaced separately from the final answer.

### 6.3 Interfaces

- **FR-10** `adk web` dev UI for local development and the primary demo surface.
- **FR-11** `POST /chat` JSON endpoint for scripted/repeatable demos.
- **FR-12** `GET /healthz` — liveness plus model reachability, for Cloud Run probes.

---

## 7. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-1 | Local first-token latency | < 3 s on M-series, model warm |
| NFR-2 | Cloud Run first-token, warm | < 2 s |
| NFR-3 | Cold start, model service | < 60 s (model baked into image, not pulled at boot) |
| NFR-4 | Agent container size | < 300 MB |
| NFR-5 | Demo-day availability | `min-instances=1` on both services; set the evening before |
| NFR-6 | Cost guardrail | Scale to zero after the talk; documented teardown command |
| NFR-7 | Reproducibility | `uv.lock` committed; pinned base images |

---

## 8. Risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Gemma tool-calling less reliable than frontier models — wrong tool, malformed args | **High** | Few-shot examples in instruction; strict typed schemas; structured-output mode; retry-once on parse failure. **Budget real time here — this is the main engineering risk.** |
| R2 | Cloud Run GPU quota unavailable in `us-central1` | Medium | Check quota *this week*; fallback = Option B (§5.2) |
| R3 | GPU cold start visible on stage | Medium | `min-instances=1`, pre-warm 15 min before, scripted warm-up call |
| R4 | 10 GB image push is slow | Medium | Build with Cloud Build, not local push; do it well before demo day |
| R5 | Conference wifi fails | Medium | **Full local fallback path rehearsed** — laptop-only demo needs no network except tool egress |
| R6 | LiteLLM ↔ Ollama function-calling translation quirks with Gemma | Medium | Validate in Phase 1 before building on it; direct OpenAI-compatible client as escape hatch |
| R7 | 8B model loops or over-calls tools | Low-Med | Hard step cap (FR-6) + loop detection on repeated identical calls |

---

## 9. Open decisions

| ID | Decision | Options | Recommendation |
|---|---|---|---|
| **D1** | Cloud model hosting | Self-host on GPU / Managed Vertex | **Self-host, with managed as env-var fallback** |
| **D2** | Demo task | Weather+math / research / dev-tools | Weather + math chain — visually obvious, keyless, reliably multi-step |
| **D3** | Talk emphasis | ADK-forward / MCP-forward / equal | Depends on audience — see §11 |
| **D4** | Repo public? | Yes / no | Yes, if audience should clone it — affects how much polish Phase 5 needs |

---

## 10. Milestones

| Phase | Deliverable | Exit criteria |
|---|---|---|
| **0. Spike** | ADK + LiteLlm + Ollama + one tool | Gemma successfully calls one function end-to-end. **Gate for R1/R6 — resolve before anything else.** |
| **1. MCP server** | 4 tools over MCP | Server passes tests standalone; MCP client lists all 4 |
| **2. Agent** | ADK agent via `MCPToolset` | 3-tool chained task completes; `adk web` shows the trace |
| **3. Containerize** | Both Dockerfiles | `docker compose up` reproduces local behaviour |
| **4. Deploy** | Cloud Run, both services | Public URL answers the demo prompt; healthchecks green |
| **5. Demo polish** | Script, fallbacks, README | Full run-through twice with no intervention |

Phase 0 is the real risk gate. Everything after it is assembly.

---

## 11. Demo script (draft)

1. **Frame it** — "Agent = model + tools + a loop that decides. Nothing more mystical than that."
2. **Show the tools** — MCP server running standalone. *These aren't in my agent. Any agent can use them.*
3. **Show the agent** — ~40 lines of ADK. Point at `MCPToolset`: the tools arrive over a protocol.
4. **Run it local** — `adk web`, ask *"What's the temperature in Lagos right now, and what is that in Fahrenheit?"* → geocode → forecast → calculator → answer. Reasoning trace visible.
5. **The turn** — "That's an 8B open model on a laptop. No API key. No frontier model."
6. **Deploy** — same prompt against the Cloud Run URL. Change one env var. Identical answer.
7. **Close** — swap-ability: ADK lets you change model, MCP lets you change tools, neither rewrite touches the other.

Emphasis per D3: engineering/platform audience → lead MCP (interop is the story). Leadership/strategy audience → lead ADK + Cloud Run (velocity, cost, no vendor lock-in on the model).

---

## 12. Repo layout (proposed)

```
gemma/
├── PRD.md
├── README.md
├── pyproject.toml / uv.lock
├── Makefile                 # dev, test, docker, deploy
├── mcp_server/
│   ├── server.py            # FastMCP entrypoint
│   └── tools/               # calculator, wikipedia, weather, clock
├── agent/
│   ├── agent.py             # ADK LlmAgent + MCPToolset
│   ├── config.py            # LLM_BASE_URL, MODEL_BACKEND, step limits
│   └── main.py              # FastAPI: /chat, /healthz
├── tests/
├── deploy/
│   ├── Dockerfile.agent
│   ├── Dockerfile.model     # ollama + gemma4 baked
│   └── deploy.sh
└── docker-compose.yml
```

---

## 13. Definition of done

- [ ] `make dev` → working agent on a clean machine, no API keys
- [ ] `make test` → green, including one end-to-end tool-calling test
- [ ] Two Cloud Run services live, healthchecks passing
- [ ] Local and cloud return equivalent answers to the demo prompt
- [ ] Offline fallback rehearsed
- [ ] README a stranger can follow
- [ ] Demo run end-to-end twice, clean
