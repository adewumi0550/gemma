# Talk submission — Build with AI 2026: Gemma Day

**Event:** GDG Ahlen · Saturday 22 August 2026 · 11:00–16:00 UTC · Virtual
**Slot:** 13:00 UTC (~30 min, matching the other sessions)
**Audience:** Founders, builders, developers — the event's stated theme is
*"fast prototyping and validating business ideas"*

---

## ⚠️ Positioning: avoid the 11:30 collision

**11:30 — "Enterprise Gemma deployment on Cloud Run" (Jay Thakkar)** already
covers deploying Gemma to Cloud Run. Leading with that would make this the
second deployment talk of the day.

**So don't lead with deployment. Lead with what happens after it.** Deployment
becomes one slide ("Jay covered this at 11:30 — here's the 60-second version"),
and the talk is really about keys, quotas, and unit economics. That's the gap on
the agenda, and it's the closest match to the event's business-validation theme.

---

## Title

**Metering Your Own AI: Gemma, MCP, and Token Quotas for Agentic Apps**

Names all three searchable terms — Gemma, MCP, token quotas — without repeating
"Cloud Run" from the 11:30 session.

---

## Abstract (~150 words — submission version)

You've got Gemma running. Now someone else wants to use it. What stops them
burning your GPU budget in an afternoon?

This session covers the part that comes after the demo: turning a self-hosted
open model into a product you can actually offer to users. We'll add API keys,
per-user token quotas, and full usage attribution to a Gemma 4 agent — every
call metered, every token accounted for.

The whole layer is built on **MCP**, so administration is itself agentic: ask an
agent to issue a key with a two-million-token quota, or to show you who's
overspending, and it does.

We'll also confront the number that surprises everyone: agentic apps consume
roughly **20× more input tokens than output**, because every reasoning step
resends the entire conversation. If you're pricing an AI product, that ratio is
your business model.

Open model. Open protocol. Your margins.

---

## Detailed description (for the organisers)

Gemma makes self-hosting viable. But "it runs" and "other people can use it" are
very different problems, and the second one is where most prototypes stall.

We start where the earlier Cloud Run session leaves off: a working Gemma 4 agent
on an L4 GPU, calling real tools and chaining them unprompted. From there we
build the operating layer.

Using the **Model Context Protocol**, we add a metering service that issues API
keys (hashed, shown once, never recoverable), enforces token quotas, and records
every call — tokens in, tokens out, tools invoked, latency, per user. Because
it's MCP, the same tools work from a script, a dashboard, or an agent, which
makes platform administration conversational.

Then the economics. Agents are input-heavy in a way that's easy to miss: each
loop iteration resends the whole conversation plus every tool schema. Measured
across real runs, that's about 20:1 input-to-output. On a metered API that's
your dominant cost. Self-hosted, it converts into latency and GPU-hours instead
— a genuine trade, and one worth understanding before you price anything.

Attendees leave with an open-source repo, a deploy script, and honest numbers,
including what an idle GPU costs when you forget to scale it down.

---

## Takeaways

1. Open models are production-viable — Gemma 4 does reliable tool calling on one L4.
2. MCP separates *what your agent does* from *who's allowed to do it*.
3. Agents are input-heavy. Measure the ratio before you price anything.
4. API keys must be hashed and shown once — a leaked database shouldn't leak access.
5. The cheapest infrastructure mistake is forgetting to scale the GPU down.

---

## Live demo

| | |
|---|---|
| Gemma 4 tool chaining | weather → calculator, unprompted |
| Issue a key over MCP | 2,000,000-token default quota |
| Quota enforcement | 429 once exhausted |
| Usage attribution | tokens, tools and latency per key |
| The 20:1 reveal | `/metrics` on real traffic |

**Virtual event, so:** pre-warm the GPU (`./deploy.sh PROJECT warm`) about 20
minutes before, rehearse over screen share, and keep the local Ollama fallback
running in a second window. Scale down afterwards.

---

## Wording notes

**"Tokenomics"** — keep it out of the title. To this audience it reads as
cryptocurrency token design. It works as a spoken aside: *"call it tokenomics if
you like — it's really just knowing who spent what."*

**"AG-UI"** — the current UI is a plain HTML page calling `/chat` and `/status`
over `fetch`. It is **not** the AG-UI protocol: no agent event stream, no
`RunAgentInput`, no CopilotKit. Say "a simple agent UI" unless it's implemented
properly — this audience will ask which events you emit.

To claim it honestly the agent would stream AG-UI events
(`TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`, `TOOL_CALL_END`, `RUN_FINISHED`)
over SSE, with the UI consuming them rather than awaiting one JSON response.
Real work, but it would make the tool-calling trace stream live on screen —
which demos far better than a four-second pause followed by a wall of text.
