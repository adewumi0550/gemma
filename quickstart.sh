#!/usr/bin/env bash
#
# Gemma 4 Agent — one-command bootstrap.
#
#   curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- local
#   curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- deploy PROJECT_ID
#
# Commands
#   local             run the agent on this machine against local Ollama
#   deploy  PROJECT   deploy agent + Gemma model to Cloud Run
#   agent   PROJECT   deploy ONLY the agent (needs LLM_BASE_URL set)
#   check             verify prerequisites and exit
#
# This clones the repo to ~/gemma-agent (override with INSTALL_DIR) because the
# Cloud Run agent build ships the whole source tree, not just one script.
#
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/adewumi0550/gemma.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/gemma-agent}"
BRANCH="${BRANCH:-main}"

CMD="${1:-}"
PROJECT="${2:-}"

bold() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m ok \033[0m %s\n' "$*"; }
bad()  { printf '\033[31mmiss\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31mError: %s\033[0m\n' "$*" >&2; exit 1; }

usage() {
  sed -n '3,17p' "$0" 2>/dev/null || cat <<'USAGE'
  local             run locally against Ollama
  deploy  PROJECT   deploy to Cloud Run (agent + GPU model)
  agent   PROJECT   deploy only the agent
  check             verify prerequisites
USAGE
  exit 1
}

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- checks

check_prereqs() {
  local need_cloud="${1:-no}"
  local missing=0

  bold "Checking prerequisites"

  if have git; then ok "git"; else bad "git — https://git-scm.com/downloads"; missing=1; fi

  if have python3; then
    ok "python3 ($(python3 --version 2>&1 | cut -d' ' -f2))"
  else
    bad "python3 — https://www.python.org/downloads/"; missing=1
  fi

  if [[ "${need_cloud}" == "yes" ]]; then
    if have gcloud; then
      ok "gcloud"
    else
      bad "gcloud — https://cloud.google.com/sdk/docs/install"; missing=1
    fi
  else
    if have ollama; then
      ok "ollama"
      if ollama list 2>/dev/null | grep -q "gemma4"; then
        ok "gemma4 model present"
      else
        bad "gemma4 not pulled — run: ollama pull gemma4  (9.6GB)"
      fi
    else
      bad "ollama — https://ollama.com/download"; missing=1
    fi
  fi

  [[ ${missing} -eq 0 ]] || die "install the missing tools above, then re-run"
}

# ---------------------------------------------------------------- fetch

fetch_repo() {
  if [[ -d "${INSTALL_DIR}/.git" ]]; then
    bold "Updating ${INSTALL_DIR}"
    git -C "${INSTALL_DIR}" fetch --quiet origin "${BRANCH}"
    git -C "${INSTALL_DIR}" checkout --quiet "${BRANCH}"
    git -C "${INSTALL_DIR}" pull --quiet --ff-only origin "${BRANCH}"
  else
    bold "Cloning into ${INSTALL_DIR}"
    git clone --quiet --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${INSTALL_DIR}"
  fi
  ok "source at ${INSTALL_DIR}"
}

# ---------------------------------------------------------------- local

run_local() {
  check_prereqs no
  fetch_repo
  cd "${INSTALL_DIR}"

  bold "Installing Python dependencies"
  python3 -m pip install --quiet --user -r requirements.txt || \
    die "pip install failed — try a virtualenv: python3 -m venv .venv && source .venv/bin/activate"
  ok "dependencies installed"

  # Loading 9.6GB from disk into memory takes a while the first time. Do it
  # now rather than inside the first user-visible request.
  bold "Warming Gemma 4 (first load can take a minute or two)"
  ollama run gemma4 "hi" >/dev/null 2>&1 || true
  ok "model warm"

  bold "Starting the agent on http://localhost:8080"
  echo "    Try:  curl -X POST localhost:8080/chat -H 'Content-Type: application/json' \\"
  echo "            -d '{\"message\":\"Temperature in Lagos, in Fahrenheit?\"}'"
  echo "    Stop: Ctrl-C"
  echo
  exec python3 app.py
}

# ---------------------------------------------------------------- deploy

run_deploy() {
  local what="$1"
  [[ -n "${PROJECT}" ]] || die "a project id is required:  ... | bash -s -- ${what} YOUR_PROJECT_ID"

  check_prereqs yes

  gcloud projects describe "${PROJECT}" >/dev/null 2>&1 || \
    die "cannot access project '${PROJECT}' — check the id, and run: gcloud auth login"
  ok "project ${PROJECT} reachable"

  fetch_repo
  cd "${INSTALL_DIR}"
  chmod +x deploy.sh

  if [[ "${what}" == "agent" ]]; then
    bold "Deploying the agent only"
    ./deploy.sh "${PROJECT}" agent
  else
    bold "Deploying the Gemma model service (GPU) — this bills while running"
    ./deploy.sh "${PROJECT}" model
    bold "Deploying the agent"
    ./deploy.sh "${PROJECT}" agent
  fi

  bold "Done"
  ./deploy.sh "${PROJECT}" urls
  echo
  echo "    Test:      cd ${INSTALL_DIR} && ./deploy.sh ${PROJECT} test"
  echo "    Stop GPU:  cd ${INSTALL_DIR} && ./deploy.sh ${PROJECT} down"
}

# ---------------------------------------------------------------- main

case "${CMD}" in
  local)  run_local ;;
  deploy) run_deploy deploy ;;
  agent)  run_deploy agent ;;
  check)  check_prereqs "${PROJECT:-no}" ;;
  ""|-h|--help|help) usage ;;
  *)      die "unknown command '${CMD}' — try: local, deploy, agent, check" ;;
esac
