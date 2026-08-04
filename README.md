# Build an Agentic AI with Gemma 4

A complete AI agent in **one file**, running on an open model you host yourself.
No API keys. No frontier model. Runs on your laptop, deploys to Cloud Run
unchanged.

Workshop material — clone it, run it, break it.

---

## What is an agent, actually?

Strip away the hype and an agent is three things:

1. **A model** that can decide what to do — here, Gemma 4.
2. **Tools** it's allowed to call — here, three Python functions.
3. **A loop** that runs tools and feeds results back until there's an answer.

That's the whole idea. [`app.py`](app.py) is those three things, labelled, in
about 200 lines.

### Why a model needs tools

Ask Gemma `What is 4728 × 391?` and it will produce a confident, wrong number.
Language models predict text; they don't calculate. Ask it today's date and it
guesses from training data.

Tools fix this. The model doesn't answer — it decides **which function to call**,
you run that function, and it uses the real result. The intelligence is choosing
the tool. The accuracy comes from the tool.

### The loop

```
user question
     │
     ▼
┌─────────────┐   "call get_weather(city='Lagos')"
│   Gemma 4   │ ──────────────────────────────────┐
└─────────────┘                                   ▼
     ▲                                    ┌──────────────┐
     │      {"temperature_celsius": 31}   │  run tool    │
     └───────────────────────────────────  └──────────────┘
     │
     ▼  (repeat until Gemma stops asking for tools)
final answer
```

Each pass, Gemma sees everything so far and either asks for another tool or
writes the answer. Chaining is where it gets interesting: *"temperature in Lagos
in Fahrenheit"* needs `get_weather` **then** `calculator`, and nobody told it
that sequence.

---

## Run it locally

**1. Install Ollama** — [ollama.com/download](https://ollama.com/download)

**2. Get Gemma 4** (~9.6 GB, one time):

```bash
ollama pull gemma4
```

**3. Warm it up.** First load pulls 9.6 GB from disk into memory and can take a
minute or two. Do this before you demo, not during:

```bash
ollama run gemma4 "hi"
```

**4. Install and run:**

```bash
pip install -r requirements.txt
```

```bash
python app.py
```

**5. Ask it something that needs tools:**

```bash
curl -X POST localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"What is the temperature in Lagos right now, and what is that in Fahrenheit?"}'
```

You'll see the tool calls in your terminal as they happen:

```
  step 1: get_weather({'city': 'Lagos'}) -> {'temperature_celsius': 31.2, ...}
  step 2: calculator({'expression': '(31.2 * 9 / 5) + 32'}) -> {'result': 88.16}
```

Two tools, chained, unprompted. That's the agent working.

---

## Usage metrics

Every response carries its own token accounting:

```json
{
  "answer": "It's 31.2°C in Lagos, which is about 88.2°F.",
  "usage": {
    "prompt": 1847,
    "completion": 96,
    "total": 1943,
    "llm_calls": 3,
    "tool_calls": 2,
    "seconds": 4.1,
    "tokens_per_second": 23.4
  }
}
```

And `GET /metrics` gives you process-wide totals:

```bash
curl localhost:8080/metrics
```

```json
{
  "requests": 12,
  "prompt_tokens": 21308,
  "completion_tokens": 1150,
  "total_tokens": 22458,
  "llm_calls": 34,
  "tool_calls": 19,
  "errors": 0,
  "by_tool": {"get_weather": 8, "calculator": 9, "current_time": 2},
  "avg_tokens_per_request": 1871.5,
  "avg_seconds_per_request": 4.32,
  "avg_tool_calls_per_request": 1.58
}
```

**The number worth pointing at in a talk:** `prompt` tokens dwarf `completion`
tokens — roughly 20:1 above. Every loop pass resends the whole conversation
*plus* every tool schema. Agents are input-heavy, and that's what drives cost on
a metered API. Here you're self-hosting, so it costs you latency instead.

`llm_calls` is the other one. Three model calls for one question — that's the
loop, made visible.

---

## Deploy to Cloud Run

The agent never imports Ollama. It only knows an OpenAI-compatible URL, so
moving to the cloud is **one environment variable**:

| Where | `LLM_BASE_URL` |
|---|---|
| Laptop | `http://localhost:11434/v1` |
| Cloud Run | `https://your-ollama-service.run.app/v1` |

**If you already have Ollama on Cloud Run**, deploy just the agent and point at it:

```bash
LLM_BASE_URL=https://YOUR-OLLAMA.run.app/v1 ./deploy.sh YOUR_PROJECT_ID agent
```

**If you don't**, `deploy.sh` will build one for you — Ollama with Gemma 4 baked
into the image, on an L4 GPU:

```bash
./deploy.sh YOUR_PROJECT_ID all
```

```bash
./deploy.sh YOUR_PROJECT_ID test
```

### Cost

The agent service is tiny and effectively free. The GPU is not.

| | |
|---|---|
| L4 GPU while running | ~$0.70–1.00 / hour |
| Build (11 GB image, one-time) | ~$0.30 |
| Image storage | ~$1 / month |
| 1-hour workshop, warmed | ~$1 |
| **Left warm and forgotten for a week** | **~$150** |

Both services scale to zero by default, so you only pay while a request is
running — at the cost of a ~60s cold start.

Before you present:

```bash
./deploy.sh YOUR_PROJECT_ID warm
```

**After you present** — this is the one that matters:

```bash
./deploy.sh YOUR_PROJECT_ID down
```

Or remove the services entirely:

```bash
./deploy.sh YOUR_PROJECT_ID destroy
```

---

## Try these

| Prompt | What it shows |
|---|---|
| `What is 4728 * 391?` | Defers to the calculator instead of guessing |
| `What's the weather in Nairobi?` | Single tool call |
| `Temperature in Lagos in Fahrenheit?` | **Chains two tools** — the good one |
| `What year is it?` | Grounding — it'd otherwise guess from training data |
| `Who was Ada Lovelace?` | No tool needed; it just answers |

That last one matters as much as the others: a good agent knows when *not* to
use a tool.

---

## Add your own tool

Three steps, all in [`app.py`](app.py):

**1. Write a function.** Return a dict; return `{"error": ...}` instead of
raising, so the model can read the failure and recover:

```python
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    rate = httpx.get(f"https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}").json()
    return {"converted": amount * rate["rates"][to_currency]}
```

**2. Register it:**

```python
TOOLS = {..., "convert_currency": convert_currency}
```

**3. Describe it in `SCHEMAS`.** This is the part people underestimate — the
description is the *only* thing Gemma uses to decide whether your tool is
relevant. A vague description is a bug, not a docs problem.

---

## How this maps to ADK and MCP

Two things you'll hear about, often presented as competing. They aren't — they
sit at different layers:

| | **This repo** | **ADK** | **MCP** |
|---|---|---|---|
| What | A hand-written loop | Agent framework | Tool protocol |
| Gives you | Understanding | Sessions, streaming, eval, deploy | Tools any agent can use |
| Analogy | Writing a socket by hand | A web framework | HTTP |

Start here so the loop isn't magic. Then **ADK** replaces the loop with a real
runtime, and **MCP** moves your tools behind a protocol so other agents can
call them too. ADK consumes MCP servers via `MCPToolset` — they compose:

```
Gemma  ←  ADK (runtime)  ←  MCPToolset  ←  MCP server (tools)
```

Neither replaces the other, and neither replaces knowing what's in `app.py`.

---

## Files

```
app.py             the entire agent — tools, metrics, loop, HTTP
requirements.txt   three dependencies
PRD.md             product spec, if you want the full design rationale
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Connection refused` | Ollama isn't running — `ollama serve` |
| First request takes ~2 min | Cold model load. Warm with `ollama run gemma4 "hi"` |
| It invents numbers instead of calling `calculator` | Sharpen the tool description; keep the "ALWAYS use the calculator" line in the system prompt |
| Loops or repeats a tool | Lower `MAX_STEPS`, or make tool descriptions more distinct |
| `model not found` | `ollama list` to check the exact tag, then set `MODEL=` to match |

---

Apache 2.0. Gemma is licensed under the
[Gemma Terms of Use](https://ai.google.dev/gemma/terms).
