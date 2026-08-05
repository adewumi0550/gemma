"""
Gemma 4 Agent — a complete agentic AI in one file.

An agent is three things: a model, some tools, and a loop that lets the
model choose which tool to call. That's it. Everything below is those three
things plus usage metrics.

Run locally:
    ollama serve
    ollama pull gemma4
    pip install fastapi uvicorn httpx
    python app.py

Deploy:
    gcloud run deploy gemma-agent --source . --region us-central1 \
      --set-env-vars LLM_BASE_URL=https://YOUR-OLLAMA.run.app/v1
"""

import json
import os
import time

import httpx
from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Optional per-user API keys and token metering. If tokenic_mcp isn't
# installed, the agent runs exactly as before — open, in-memory metrics only.
try:
    from tokenic_mcp.middleware import meter, require_key
    TOKENIC = True
except ImportError:  # pragma: no cover
    TOKENIC = False

    def require_key():
        return None

    def meter(*_args, **_kwargs):
        return None

# --- config: one env var moves this between laptop and cloud -----------------

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.getenv("MODEL", "gemma4")

# What the status page shows. The tag ("gemma4") is what Ollama needs; this is
# what a human should read.
MODEL_LABEL = os.getenv("MODEL_LABEL", "Gemma 4")
MAX_STEPS = int(os.getenv("MAX_STEPS", "6"))
PORT = int(os.getenv("PORT", "8080"))


# --- 1. TOOLS ---------------------------------------------------------------
# Plain Python functions. No API keys anywhere — nothing to provision, nothing
# to leak on a slide.

def calculator(expression: str) -> dict:
    """Do maths. Gemma is a language model, not a calculator — always defer."""
    try:
        # eval() on model output is unsafe; allow digits and operators only.
        if not set(expression) <= set("0123456789+-*/.() "):
            return {"error": "only numbers and + - * / ( ) allowed"}
        return {"result": eval(expression)}
    except Exception as e:
        return {"error": str(e)}


def get_weather(city: str) -> dict:
    """Current weather, via Open-Meteo. Two hops: city -> coords -> forecast."""
    try:
        geo = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1}, timeout=10,
        ).json()
        if not geo.get("results"):
            return {"error": f"unknown city: {city}"}
        spot = geo["results"][0]
        now = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={"latitude": spot["latitude"], "longitude": spot["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m"},
            timeout=10,
        ).json()["current"]
        return {
            "location": f"{spot['name']}, {spot.get('country')}",
            "temperature_celsius": now["temperature_2m"],
            "humidity_percent": now["relative_humidity_2m"],
            "wind_kmh": now["wind_speed_10m"],
        }
    except Exception as e:
        return {"error": str(e)}


def current_time() -> dict:
    """Today's date. A model can only guess this from training data."""
    return {"utc": time.strftime("%A, %d %B %Y, %H:%M UTC", time.gmtime())}


TOOLS = {"calculator": calculator, "get_weather": get_weather, "current_time": current_time}

# Gemma picks tools by reading these descriptions — so the wording is code,
# not documentation. Vague descriptions produce wrong tool choices.
SCHEMAS = [
    {"type": "function", "function": {
        "name": "calculator",
        "description": "Evaluate a maths expression. Use for ANY arithmetic, however simple.",
        "parameters": {"type": "object", "required": ["expression"], "properties": {
            "expression": {"type": "string", "description": "e.g. '(31 * 9 / 5) + 32'"}}}}},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "Current weather for a city: temperature, humidity, wind.",
        "parameters": {"type": "object", "required": ["city"], "properties": {
            "city": {"type": "string", "description": "e.g. 'Lagos'"}}}}},
    {"type": "function", "function": {
        "name": "current_time",
        "description": "Today's date and time in UTC. Use for anything about now.",
        "parameters": {"type": "object", "properties": {}}}},
]


# --- 2. METRICS -------------------------------------------------------------
# Ollama returns token counts in the OpenAI-compatible `usage` block. We add
# them up per request and across the process.

METRICS = {
    "requests": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "tool_calls": 0,
    "llm_calls": 0,
    "errors": 0,
    "total_seconds": 0.0,
    "by_tool": {},
    "started": time.time(),
}


def record(usage: dict) -> dict:
    """Fold one LLM response's usage into the running totals."""
    used = {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
    METRICS["llm_calls"] += 1
    for k, v in used.items():
        METRICS[k] += v
    return used


# --- 3. THE AGENT LOOP ------------------------------------------------------

SYSTEM = """You are a helpful assistant with tools.

- ALWAYS use the calculator for arithmetic. Never compute numbers yourself.
- ALWAYS use current_time for anything about today or now.
- You can chain tools: feed one result into the next call.
- When you have enough, answer in plain language. Don't mention the tools."""


def run_agent(question: str) -> dict:
    started = time.time()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": question}]
    trace, tokens = [], {"prompt": 0, "completion": 0, "total": 0}

    METRICS["requests"] += 1
    client = httpx.Client(base_url=LLM_BASE_URL, timeout=300,
                          headers={"Authorization": "Bearer ollama"})

    try:
        for step in range(1, MAX_STEPS + 1):
            # --- ask the model what to do next
            reply = client.post("/chat/completions", json={
                "model": MODEL, "messages": messages,
                "tools": SCHEMAS, "temperature": 0.3, "stream": False,
            })
            reply.raise_for_status()
            body = reply.json()

            used = record(body.get("usage", {}))
            tokens["prompt"] += used["prompt_tokens"]
            tokens["completion"] += used["completion_tokens"]
            tokens["total"] += used["total_tokens"]

            message = body["choices"][0]["message"]
            messages.append(message)
            calls = message.get("tool_calls") or []

            # --- no tool wanted? then it's the final answer
            if not calls:
                elapsed = round(time.time() - started, 2)
                METRICS["total_seconds"] += elapsed
                return {
                    "answer": (message.get("content") or "").strip(),
                    "trace": trace,
                    "usage": {**tokens, "llm_calls": step, "tool_calls": len(trace),
                              "seconds": elapsed,
                              "tokens_per_second": round(tokens["completion"] / elapsed, 1) if elapsed else 0},
                }

            # --- otherwise run every tool it asked for
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                fn = TOOLS.get(name)
                result = fn(**args) if fn else {"error": f"no such tool: {name}"}

                METRICS["tool_calls"] += 1
                METRICS["by_tool"][name] = METRICS["by_tool"].get(name, 0) + 1
                trace.append({"step": step, "tool": name, "args": args, "result": result})
                print(f"  step {step}: {name}({args}) -> {result}")

                messages.append({"role": "tool", "tool_call_id": call.get("id", name),
                                 "name": name, "content": json.dumps(result)})

        return {"answer": "Ran out of steps.", "trace": trace, "usage": tokens}

    except Exception as e:
        METRICS["errors"] += 1
        return {"answer": f"Error: {e}", "trace": trace, "usage": tokens}
    finally:
        client.close()


# --- 4. HTTP ----------------------------------------------------------------

app = FastAPI(title="Gemma 4 Agent")


class Ask(BaseModel):
    message: str


@app.post("/chat")
def chat(ask: Ask, key=Depends(require_key)):
    result = run_agent(ask.message)
    # Attribute the tokens to whoever's key made the call. No-op if unauthenticated.
    meter(key, result, model=MODEL, endpoint="/chat")
    if key is not None:
        result["billed_to"] = {"key_id": key.id, "owner": key.owner,
                               "tokens_remaining": key.tokens_remaining}
    return result


@app.get("/metrics")
def metrics():
    """Usage tracking — tokens, tool calls, cost proxy, averages."""
    uptime = time.time() - METRICS["started"]
    requests = max(METRICS["requests"], 1)
    return {
        **{k: v for k, v in METRICS.items() if k != "started"},
        "uptime_seconds": round(uptime, 1),
        "avg_tokens_per_request": round(METRICS["total_tokens"] / requests, 1),
        "avg_seconds_per_request": round(METRICS["total_seconds"] / requests, 2),
        "avg_tool_calls_per_request": round(METRICS["tool_calls"] / requests, 2),
    }


@app.get("/healthz")
def healthz():
    try:
        ok = httpx.get(f"{LLM_BASE_URL}/models", timeout=5).status_code < 400
    except Exception:
        ok = False
    return {"status": "ok" if ok else "degraded", "model": MODEL, "llm": LLM_BASE_URL}


def _model_up() -> bool:
    try:
        return httpx.get(f"{LLM_BASE_URL}/models", timeout=5).status_code < 400
    except Exception:
        return False


@app.get("/", response_class=HTMLResponse)
def home():
    """Status page. Ollama's own root says 'Ollama is running' — this says
    what the audience actually cares about."""
    up = _model_up()
    dot = "#1D9E75" if up else "#D85A30"
    state = f"{MODEL_LABEL} is running" if up else f"{MODEL_LABEL} is unreachable"
    tools = "".join(f"<code>{t}</code>" for t in TOOLS)
    return f"""<!doctype html>
<meta charset="utf-8"><title>{MODEL_LABEL} is running</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;max-width:40rem;
      margin:4rem auto;padding:0 1.5rem;line-height:1.6;color:#1c1c1a}}
 h1{{font-size:1.9rem;margin:0 0 .3rem;display:flex;align-items:center;gap:.6rem}}
 .dot{{width:.7rem;height:.7rem;border-radius:50%;background:{dot};flex:none}}
 .sub{{color:#5f5e5a;margin:0 0 2rem}}
 code{{background:#f1efe8;padding:.15rem .45rem;border-radius:4px;font-size:.87em;
       margin-right:.3rem;display:inline-block}}
 input{{width:100%;padding:.75rem;font-size:1rem;border:1px solid #d3d1c7;
        border-radius:8px;box-sizing:border-box}}
 pre{{background:#f1efe8;padding:1rem;border-radius:8px;overflow-x:auto;font-size:.85rem}}
 .lbl{{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;
       color:#888780;margin:1.6rem 0 .4rem}}
 .ans{{font-size:1.05rem;margin:.8rem 0}}
</style>
<h1><span class="dot"></span>{state}</h1>
<p class="sub">Agentic AI · {MODEL} served by Ollama · {"Cloud Run" if "localhost" not in LLM_BASE_URL else "local"}</p>

<div class="lbl">Tools</div>
<div>{tools}</div>

<div class="lbl">Ask it something</div>
<input id="q" placeholder="What's the temperature in Lagos, and what is that in Fahrenheit?"
       autofocus onkeydown="if(event.key==='Enter')ask()">
<div id="out"></div>

<div class="lbl">Endpoints</div>
<div><code>POST /chat</code><code>GET /metrics</code><code>GET /healthz</code></div>

<script>
async function ask() {{
  const q = document.getElementById('q').value.trim();
  const out = document.getElementById('out');
  if (!q) return;
  out.innerHTML = '<p class="ans">thinking…</p>';
  try {{
    const r = await fetch('/chat', {{method:'POST',
      headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{message:q}})}});
    const d = await r.json();
    const trace = (d.trace||[]).map(t =>
      t.tool + '(' + JSON.stringify(t.args) + ')\\n  -> ' + JSON.stringify(t.result)
    ).join('\\n\\n');
    out.innerHTML = '<p class="ans"></p><div class="lbl">'
      + (d.usage ? d.usage.total + ' tokens · ' + (d.usage.llm_calls||0) + ' model calls · '
                 + (d.usage.tool_calls||0) + ' tool calls' : '')
      + '</div>' + (trace ? '<pre></pre>' : '');
    out.querySelector('.ans').textContent = d.answer || '(no answer)';
    if (trace) out.querySelector('pre').textContent = trace;
  }} catch (e) {{ out.innerHTML = '<p class="ans">request failed: ' + e + '</p>'; }}
}}
</script>
"""


@app.get("/status")
def status():
    """Same thing as JSON, for scripts."""
    return {
        "status": f"{MODEL_LABEL} is running" if _model_up() else f"{MODEL_LABEL} is unreachable",
        "model": MODEL,
        "served_by": LLM_BASE_URL,
        "tools": list(TOOLS),
    }


if __name__ == "__main__":
    import uvicorn
    print(f"Gemma agent -> {LLM_BASE_URL} ({MODEL}), tools: {', '.join(TOOLS)}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
