# Talk abstract

## Title

**Metering Your Own AI: Gemma, MCP, and Token Quotas on Cloud Run**

*Alternate subtitle:* …for Agentic Apps

---

## Short abstract (CFP / programme, ~120 words)

Every "build an agent" talk ends at a working demo. This one starts there.

We'll build an agentic AI on **Gemma 4** — an open model you host yourself, no
frontier API, no keys — running on Cloud Run with an L4 GPU. It calls real
tools, chains them unprompted, and shows its reasoning.

Then the part nobody covers: **how do you let other people use it without going
bankrupt?**

We'll wire in an **MCP server** that issues API keys, enforces token quotas, and
attributes every token to a user — administered entirely through MCP tools, so
an agent can run the billing platform. Along the way: why agents burn 20× more
input tokens than output, and what that means for your bill.

Open model. Open protocol. Your infrastructure. Your economics.

---

## Long abstract (~280 words)

Agents are easy to demo and hard to operate. The gap shows up the moment
someone else wants to use yours.

This session builds the whole path. We start with **Gemma 4** running under
Ollama — first on a laptop, then on Cloud Run with an NVIDIA L4 — and write an
agent loop from scratch, because the loop is the part everyone treats as magic.
It's about sixty lines: a model, some tools, and a loop that lets the model
choose. We'll watch it chain a weather lookup into a calculator without being
told to, and watch it refuse to do arithmetic in its head.

Then we make it a service other people can call.

Using the **Model Context Protocol**, we build a metering layer that issues API
keys, enforces per-key token quotas, and records every call — tokens in, tokens
out, tools invoked, latency. Crucially, the whole thing is exposed as **MCP
tools**, so administration is itself agentic: ask an agent to issue a key with a
two-million-token quota, or to tell you who's overspending, and it does.

Along the way we'll confront the numbers that make agents expensive. Every loop
iteration resends the entire conversation *plus* every tool schema, so agents
run roughly **20:1 input-to-output tokens**. Self-hosting converts that cost
from dollars into latency and GPU-hours — a trade worth understanding before you
commit to either.

You'll leave with a working repo, a deployment script, and an honest account of
what it costs — including what happens when you forget to scale the GPU down.

**Level:** Intermediate · **Format:** 40 min talk + live demo

---

## Takeaways

1. An agent is a model, tools, and a loop — build it once by hand and it stops being mysterious.
2. Open models are production-viable: Gemma 4 does reliable tool calling on a single L4.
3. MCP separates *what your agent can do* from *who's allowed to do it*.
4. Agents are input-heavy. Measure tokens before you price anything.
5. Portability is one environment variable — if you design for it.

---

## What's demoed live

| | |
|---|---|
| Gemma 4 on Cloud Run | L4 GPU, model baked into the image |
| Tool chaining | weather → calculator, unprompted |
| MCP key issuing | 2,000,000-token default quota |
| Quota enforcement | 429 when exhausted |
| Usage attribution | per-key tokens, tools, latency |

---

## Notes on wording

**"Tokenomics"** — avoid it in the title. To a developer audience it means
cryptocurrency token design, and it will attract the wrong people while
repelling the right ones. It works as a spoken aside: *"call it tokenomics if
you like — it's really just knowing who spent what."*

**"AG-UI"** — the current UI is a plain HTML page calling `/chat` and `/status`
over `fetch`. It is **not** the AG-UI protocol: no agent-event stream, no
`RunAgentInput`, no CopilotKit integration. Say "a simple agent UI" unless you
implement AG-UI properly — an audience that knows the protocol will ask which
events you emit.

To claim it honestly, the agent would need to stream AG-UI events
(`TEXT_MESSAGE_CONTENT`, `TOOL_CALL_START`, `TOOL_CALL_END`, `RUN_FINISHED`)
over SSE, and the UI would consume them instead of awaiting one JSON response.
That's a real addition, not a relabel — but it would make the tool-calling
trace stream live on screen, which demos well.
