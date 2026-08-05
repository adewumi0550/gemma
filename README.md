<div align="center">

# Build an Agentic AI with Gemma 4

**A complete AI agent in one file — on an open model you host yourself.**

No API keys. No frontier model. Runs on your laptop, deploys to Cloud Run unchanged.

[![Model](https://img.shields.io/badge/model-Gemma%204%20(8B)-1D9E75)](https://ai.google.dev/gemma)
[![Runtime](https://img.shields.io/badge/runtime-Ollama-534AB7)](https://ollama.com)
[![Deploy](https://img.shields.io/badge/deploy-Cloud%20Run-378ADD)](https://cloud.google.com/run)
[![License](https://img.shields.io/badge/license-Apache%202.0-5F5E5A)](LICENSE)

</div>

---

## What you'll build

An agent that answers *"What's the temperature in Lagos, and what is that in Fahrenheit?"* by calling a weather API, then a calculator — chaining two tools it was never told to chain.

Then you'll put it in production with per-user API keys and token metering.

![Deployment topology](diagrams/01-deployment-topology.svg)

Two Cloud Run services. The agent is ~200 MB and redeploys in two minutes; the model is ~11 GB and needs a GPU. Splitting them means a prompt tweak doesn't re-push 11 GB.

---

## Contents

| | |
|---|---|
| [Quick start](#quick-start) | One command, laptop or cloud |
| [What is an agent?](#what-is-an-agent-actually) | The three-part idea, no hype |
| [Run it locally](#run-it-locally) | Step by step |
| [Usage metrics](#usage-metrics) | Token accounting per request |
| [API keys & metering](#api-keys--metering) | `tokenic_mcp` — 9 MCP tools |
| [Deploy to Cloud Run](#deploy-to-cloud-run) | Including what it costs |
| [Add your own tool](#add-your-own-tool) | Three steps |
| [ADK and MCP](#how-this-maps-to-adk-and-mcp) | Where this sits |
| [Running the workshop](#running-the-workshop) | If you're presenting this |
| [Troubleshooting](#troubleshooting) | Real failures, real fixes |

---

## Quick start

Run it on your machine:

```bash
curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- local
```

Deploy to Cloud Run — replace `YOUR_PROJECT_ID` with your own Google Cloud project ID ([how to find it](#first-your-project-id)):

```bash
curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- deploy YOUR_PROJECT_ID
```

Check prerequisites without installing anything:

```bash
curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- check
```

> **Piping a URL into `bash` runs code you haven't read.** Fine here — it's a
> short script you can read first, and you should build the habit:
>
> ```bash
> curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh -o quickstart.sh && less quickstart.sh && bash quickstart.sh local
> ```

---

## What is an agent, actually?

Strip away the hype and an agent is three things:

1. **A model** that decides what to do — here, Gemma 4.
2. **Tools** it may call — here, three Python functions.
3. **A loop** that runs tools and feeds results back until there's an answer.

That's it. [`app.py`](app.py) is those three things, labelled, in ~260 lines.

### Why a model needs tools

Ask Gemma `What is 4728 × 391?` and you'll get a confident, wrong number. Language models predict text; they don't calculate. Ask today's date and it guesses from training data.

Tools fix this. The model doesn't answer — it decides **which function to call**, you run it, and it uses the real result.

> **The intelligence is choosing the tool. The accuracy comes from the tool.**

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

Each pass, Gemma sees everything so far and either asks for another tool or writes the answer. Chaining is where it gets interesting: *"temperature in Lagos in Fahrenheit"* needs `get_weather` **then** `calculator`, and nobody told it that sequence.

---

## Run it locally

**1. Install Ollama** — [ollama.com/download](https://ollama.com/download)

**2. Get Gemma 4** (~9.6 GB, one time):

```bash
ollama pull gemma4
```

**3. Warm it.** First load pulls 9.6 GB from disk into memory and can take a minute or two. Do this *before* you demo:

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

Open **http://localhost:8080** — a status page that says **“Gemma 4 is running”**, with a live model check, the tool list, and a box to ask questions.

> Hitting Ollama directly (`:11434`) says *“Ollama is running”* — that's Ollama's
> own root handler and can't be changed. The agent's page is the one to put on
> screen; rename it with `MODEL_LABEL="Gemma 4"` if you switch models.

**5. Or ask from the terminal:**

```bash
curl -X POST localhost:8080/chat -H 'Content-Type: application/json' -d '{"message":"What is the temperature in Lagos right now, and what is that in Fahrenheit?"}'
```

Tool calls print as they happen:

```
  step 1: get_weather({'city': 'Lagos'}) -> {'temperature_celsius': 31.2, ...}
  step 2: calculator({'expression': '(31.2 * 9 / 5) + 32'}) -> {'result': 88.16}
```

Two tools, chained, unprompted. That's the agent working.

### Try these

| Prompt | What it shows |
|---|---|
| `What is 4728 * 391?` | Defers to the calculator instead of guessing |
| `What's the weather in Nairobi?` | Single tool call |
| **`Temperature in Lagos in Fahrenheit?`** | **Chains two tools — the good one** |
| `What year is it?` | Grounding; it'd otherwise guess from training data |
| `Who was Ada Lovelace?` | No tool needed — it just answers |

That last one matters as much as the others: a good agent knows when *not* to use a tool.

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

`GET /metrics` gives process-wide totals:

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
  "by_tool": {"get_weather": 8, "calculator": 9, "current_time": 2},
  "avg_tokens_per_request": 1871.5,
  "avg_seconds_per_request": 4.32
}
```

> **The number worth pointing at:** prompt tokens dwarf completion tokens — about **20:1** above. Every loop pass resends the whole conversation *plus* every tool schema. Agents are input-heavy, and that's what drives cost on a metered API. Self-hosting, it costs you latency instead.

`llm_calls: 34` across 12 requests is the other one — roughly 3 model calls per question. That's the loop, made visible.

---

## API keys & metering

[`tokenic_mcp/`](tokenic_mcp/) turns the agent into something you can hand to other people: per-user API keys, token quotas, and usage tracking — all administered through **MCP tools**.

![Metered request flow](diagrams/02-metered-request-flow.svg)

Note the split at the agent: one path goes to the GPU, the other writes token counts to storage. They're independent — **metering fails open**, so if the database is down the user still gets their answer; you just lose the billing record.

`tokenic_mcp` sits *under* the store, not in the request path. It never touches a user request.

### The 9 MCP tools

| Keys | Usage |
|---|---|
| `issue_api_key` | `get_usage` |
| `revoke_api_key` | `get_total_usage` |
| `list_api_keys` | `recent_calls` |
| `describe_api_key` | `top_consumers` |
| | `check_quota` |

### Turn it on

```bash
TOKENIC_REQUIRE_KEY=true TOKENIC_BACKEND=firestore python app.py
```

Calls then need a key, and responses gain a `billed_to` block:

```json
{
  "answer": "It's 25.6°C in Lagos…",
  "usage": {"total": 1943, "tool_calls": 2},
  "billed_to": {"key_id": "key_a1b2…", "owner": "ada", "tokens_remaining": 3057}
}
```

**401** for a bad or revoked key, **429** when the quota is gone.

### Storage

| `TOKENIC_BACKEND` | Use when |
|---|---|
| `memory` *(default)* | Workshops, local dev. Zero setup, lost on restart |
| `firestore` | You want serverless — matches Cloud Run, no pool to manage |
| `postgres` | You'll bill from this data — SQL aggregation, monthly rollup view |

Every new key gets **2,000,000 tokens** by default. Change it with
`TOKENIC_DEFAULT_QUOTA`, or per key with `issue_api_key(token_quota=…)` — `0`
issues an unlimited key. Once exhausted, calls get **429**.

### Adding a Postgres URL

Three ways to supply it, in order of precedence:

**1. Environment variable** — highest precedence, good for a one-off test:

```bash
export DATABASE_URL='postgresql://user:password@host:5432/dbname'
```

**2. A `.env` file** — what most people want locally:

```bash
cp tokenic_mcp/.env.example tokenic_mcp/.env
```

Edit it, set `TOKENIC_BACKEND=postgres` and your `DATABASE_URL`. The file is
gitignored — **never commit a real one**.

**3. On Cloud Run** — use the unix socket, not a public IP:

```bash
gcloud run deploy tokenic --source . --region us-central1 --add-cloudsql-instances PROJECT:REGION:INSTANCE --set-env-vars TOKENIC_BACKEND=postgres,DATABASE_URL='postgresql://user:pass@/dbname?host=/cloudsql/PROJECT:REGION:INSTANCE'
```

### Then test it

```bash
python -m tokenic_mcp.check
```

That connects, creates the schema, issues a key, meters usage, verifies quota
enforcement, and cleans up after itself. It prints your URL with the password
masked, so the output is safe to paste when asking for help.

Run it **before** a workshop. Finding out your database is unreachable while
thirty people watch is a bad way to learn.

> **If your password contains `@ : / ? # $`, URL-encode it** — this is the most
> common connection failure. `$` becomes `%24`, `@` becomes `%40`:
>
> ```bash
> python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" 'your-password'
> ```

Common failures the check will name for you:

| Symptom | Cause |
|---|---|
| `ConnectionTimeout` | Cloud SQL **Authorized networks** doesn't include your IP, or a firewall blocks 5432 |
| `authentication failed` | Wrong password, or special characters not URL-encoded |
| `driver missing` | `pip install "psycopg[binary]" psycopg-pool` |

Keys are stored as **SHA-256 only** and shown exactly once. A database dump leaks nothing usable. Full detail in [`tokenic_mcp/README.md`](tokenic_mcp/README.md).

---

## Deploy to Cloud Run

### First: your project ID

Every deploy command needs **your own Google Cloud project ID** — not a project name, not a number. It looks like `my-project-4f2a1` or `steadfast-helix-429321-b2`.

**1. Sign in:**

```bash
gcloud auth login
```

**2. Find your project ID** (the `PROJECT_ID` column):

```bash
gcloud projects list
```

No projects? Create one — the ID must be globally unique, so add a suffix:

```bash
gcloud projects create my-gemma-agent-4f2a1 --name="Gemma Agent"
```

**3. Set it as your default** so you don't retype it:

```bash
gcloud config set project YOUR_PROJECT_ID
```

**4. Enable billing.** Cloud Run and GPUs need an active billing account — a free-trial account works. Check with:

```bash
gcloud beta billing projects describe YOUR_PROJECT_ID
```

If that prints `billingEnabled: false`, link an account in the [console](https://console.cloud.google.com/billing) first. Every deploy will fail until you do.

Then substitute your ID wherever this README says `YOUR_PROJECT_ID`:

```bash
./deploy.sh my-gemma-agent-4f2a1 all
```

### Second: your region

**Pick a region near you** — it's the difference between 40 ms and 300 ms of network latency on every call, and it may matter for where your data sits.

But **not every Cloud Run region has L4 GPUs.** See the current list:

```bash
curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- regions
```

| Region | Location |
|---|---|
| `us-central1` *(default)* | Iowa |
| `us-east4` | N. Virginia |
| `us-west1` | Oregon |
| `europe-west1` | Belgium |
| `europe-west4` | Netherlands |
| `europe-north1` | Finland |
| `asia-southeast1` | Singapore |
| `asia-south1` | Mumbai |
| `asia-northeast1` | Tokyo |
| `australia-southeast1` | Sydney |

Pass it as the **third argument**:

```bash
curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- deploy YOUR_PROJECT_ID europe-west4
```

Or set `REGION` — `deploy.sh` reads it from the environment:

```bash
REGION=asia-south1 ./deploy.sh YOUR_PROJECT_ID all
```

Omit both and you get an interactive picker. Precedence is **argument → `REGION` → prompt → `us-central1`**.

> **Africa, South America, and the Middle East have no L4 Cloud Run region yet.**
> From Lagos, `europe-west1` (Belgium) is usually the lowest-latency option;
> from São Paulo, `us-east4`. The script warns if you pick a region not on the
> list rather than blocking you — Google adds regions, and this table will age.

Region availability shifts, so confirm against the [official GPU region list](https://cloud.google.com/run/docs/configuring/services/gpu) before a workshop.

> The script takes the project ID as its **first argument** — it doesn't read
> your gcloud default. That's deliberate: with a room full of people deploying
> at once, an explicit ID beats a silent default that deploys to the wrong place.

---

### Moving to the cloud

The agent never imports Ollama. It only knows an OpenAI-compatible URL, so moving to the cloud is **one environment variable**:

| Where | `LLM_BASE_URL` |
|---|---|
| Laptop | `http://localhost:11434/v1` |
| Cloud Run | `https://your-model-service.run.app/v1` |

**Already have Ollama on Cloud Run?** Deploy just the agent:

```bash
LLM_BASE_URL=https://YOUR-OLLAMA.run.app/v1 ./deploy.sh YOUR_PROJECT_ID agent
```

**Don't?** `deploy.sh` builds one — Ollama with Gemma 4 baked into the image, on an L4 GPU:

```bash
./deploy.sh YOUR_PROJECT_ID all
```

```bash
./deploy.sh YOUR_PROJECT_ID test
```

### What it costs

The agent service is effectively free. The GPU is not.

| | |
|---|---|
| L4 GPU while running | ~$0.70–1.00 / hour |
| Build (11 GB image, one-time) | ~$0.30 |
| Image storage | ~$1 / month |
| 1-hour workshop, warmed | ~$1 |
| **Left warm and forgotten for a week** | **~$150** |

Both services scale to zero by default — you pay only while a request runs, at the cost of a ~60s cold start.

Before you present:

```bash
./deploy.sh YOUR_PROJECT_ID warm
```

**After you present** — the one that matters:

```bash
./deploy.sh YOUR_PROJECT_ID down
```

Or remove everything:

```bash
./deploy.sh YOUR_PROJECT_ID destroy
```

### Push-to-deploy

[`cloudbuild.yaml`](cloudbuild.yaml) redeploys the **agent** on every push to `main`. The model image is deliberately excluded — you don't want a 25-minute GPU rebuild on a README typo.

```bash
gcloud builds triggers create github --name=gemma-agent-deploy --repo-name=gemma --repo-owner=adewumi0550 --branch-pattern="^main$" --build-config=cloudbuild.yaml --region=us-central1
```

---

## Add your own tool

Three steps, all in [`app.py`](app.py):

**1. Write a function.** Return a dict; return `{"error": ...}` instead of raising, so the model can read the failure and recover:

```python
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    rate = httpx.get(f"https://api.frankfurter.app/latest?from={from_currency}&to={to_currency}").json()
    return {"converted": amount * rate["rates"][to_currency]}
```

**2. Register it:**

```python
TOOLS = {..., "convert_currency": convert_currency}
```

**3. Describe it in `SCHEMAS`.** The part people underestimate — the description is the *only* thing Gemma uses to decide whether your tool is relevant.

> **A vague tool description is a bug, not a docs problem.**

---

## How this maps to ADK and MCP

Two things you'll hear about, often presented as competing. They aren't — they sit at different layers:

| | **This repo** | **ADK** | **MCP** |
|---|---|---|---|
| What | A hand-written loop | Agent framework | Tool protocol |
| Gives you | Understanding | Sessions, streaming, eval, deploy | Tools any agent can use |
| Analogy | Writing a socket by hand | A web framework | HTTP |

Start here so the loop isn't magic. Then **ADK** replaces the loop with a real runtime, and **MCP** moves your tools behind a protocol so other agents can call them. ADK consumes MCP servers via `MCPToolset` — they compose:

```
Gemma  ←  ADK (runtime)  ←  MCPToolset  ←  MCP server (tools)
```

Neither replaces the other, and neither replaces knowing what's in `app.py`.

### The five layers

Worth being explicit about early — if two of these get conflated, the architecture stops making sense:

| Layer | What it is |
|---|---|
| **Gemma** | The model — trained weights |
| **Ollama** | The runtime that loads and serves them |
| **ADK** | The agent framework — loop, sessions |
| **MCP** | The tool protocol |
| **Cloud Run** | Where the containers run |

---

## Running the workshop

If you're presenting this:

**The week before**

- [ ] Check Cloud Run **L4 GPU quota** in your region — approval isn't instant
- [ ] Run the model build once: `./deploy.sh PROJECT model` (~30–45 min)
- [ ] Send participants the `check` command so they arrive with Ollama installed
- [ ] Tell participants to bring a **Google Cloud project with billing enabled** — creating one and linking billing takes longer than you'd think, and it blocks every deploy command

**The day of**

- [ ] `./deploy.sh PROJECT warm` — about 20 minutes ahead
- [ ] `ollama run gemma4 "hi"` on your laptop, so no 160s cold load on stage
- [ ] Have the local fallback ready in case conference wifi dies

**Afterwards**

- [ ] `./deploy.sh PROJECT down` — **this is the one people forget**

### Demo arc

1. **Frame it** — an agent is a model, tools, and a loop. Nothing more mystical.
2. **Break it first** — ask `What is 4728 * 391?` with tools disabled. Wrong answer. *This is why tools exist.*
3. **Turn tools on** — same question, right answer, visible tool call.
4. **Chain them** — the Lagos-to-Fahrenheit prompt. Two tools, unprompted.
5. **Show the cost** — `/metrics`, and the 20:1 input ratio.
6. **Deploy** — same prompt against Cloud Run. One env var changed.
7. **Close** — swap the model, swap the tools, neither rewrite touches the other.

---

## Files

```
app.py                  the entire agent — tools, metrics, loop, HTTP
quickstart.sh           one-command bootstrap (local or deploy)
deploy.sh               Cloud Run: model | agent | test | warm | down | destroy
cloudbuild.yaml         push-to-deploy for the agent
Dockerfile.agent        agent container
requirements.txt        three dependencies

tokenic_mcp/            API keys + token metering, over MCP
├── server.py           the MCP server (9 tools)
├── metering.py         key lifecycle + usage logic
├── keys.py             generation, hashing, constant-time verify
├── middleware.py       FastAPI auth dependency
├── schema.sql          Postgres DDL + monthly rollup
└── storage/            memory · firestore · postgres

diagrams/               architecture diagrams (SVG + 3x PNG)
PRD.md                  full design rationale
```

---

## Troubleshooting

### Local

| Problem | Fix |
|---|---|
| `Connection refused` | Ollama isn't running — `ollama serve` |
| First request takes ~2 min | Cold model load. Warm with `ollama run gemma4 "hi"` |
| It invents numbers instead of calling `calculator` | Sharpen the tool description; keep the "ALWAYS use the calculator" line in the system prompt |
| Loops or repeats a tool | Lower `MAX_STEPS`, or make tool descriptions more distinct |
| `model not found` | `ollama list` for the exact tag, then set `MODEL=` to match |

### Cloud Run

| Problem | Fix |
|---|---|
| `FAILED_PRECONDITION: cannot run builds of this machine type` | Cloud Build machine quota. The default builder is used now; to try a bigger one: `BUILD_MACHINE=E2_HIGHCPU_8 ./deploy.sh …` |
| `Quota exceeded: NVIDIA_L4_GPUS` | Request GPU quota in the console, or point `LLM_BASE_URL` at a managed endpoint |
| Build times out | Already 3600s. An 11 GB image on the default builder takes 30–45 min |
| Agent returns 502 | Model still loading — wait ~60s, check `/healthz` |
| `/healthz` says `degraded` | Agent can't reach the model. Check `LLM_BASE_URL` and invoker IAM |
| Container fails to start | Ollama must bind `0.0.0.0:8080` — Cloud Run routes nowhere else |

---

## License

Apache 2.0. Gemma is separately licensed under the [Gemma Terms of Use](https://ai.google.dev/gemma/terms).
