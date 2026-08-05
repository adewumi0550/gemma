#!/usr/bin/env bash
#
# Gemma 4 Agent — one-command bootstrap.
#
#   curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- local
#   curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- deploy PROJECT_ID
#   curl -sSL https://raw.githubusercontent.com/adewumi0550/gemma/main/quickstart.sh | bash -s -- deploy PROJECT_ID europe-west4
#
# Commands
#   local                    run the agent on this machine against local Ollama
#   deploy  PROJECT [REGION] deploy agent + Gemma model to Cloud Run
#   agent   PROJECT [REGION] deploy ONLY the agent (needs LLM_BASE_URL set)
#   regions                  list Cloud Run regions that offer L4 GPUs
#   check                    verify prerequisites and exit
#
# Region: pass it as the 3rd argument, or set REGION=. Omit both and you get an
# interactive picker (or us-central1 when there's no terminal to prompt on).
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
REGION_ARG="${3:-}"

# Cloud Run regions that offered NVIDIA L4 at time of writing. Google adds to
# this list, so an unlisted region is a warning, not a refusal — check current
# availability at cloud.google.com/run/docs/configuring/services/gpu
GPU_REGIONS=(
  us-central1        # Iowa
  us-east4           # N. Virginia
  us-west1           # Oregon
  europe-west1       # Belgium
  europe-west4       # Netherlands
  europe-north1      # Finland
  asia-southeast1    # Singapore
  asia-south1        # Mumbai
  asia-northeast1    # Tokyo
  australia-southeast1  # Sydney
)

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

# ---------------------------------------------------------------- region

list_regions() {
  bold "Cloud Run regions with NVIDIA L4 GPUs"
  local i=1
  for r in "${GPU_REGIONS[@]}"; do
    printf '  %2d) %s\n' "${i}" "${r}"
    i=$((i + 1))
  done
  printf '\n  Availability changes — current list:\n'
  printf '  https://cloud.google.com/run/docs/configuring/services/gpu\n'
}

is_gpu_region() {
  local candidate="$1"
  for r in "${GPU_REGIONS[@]}"; do
    [[ "${r}" == "${candidate}" ]] && return 0
  done
  return 1
}

# Order of preference: 3rd argument, then $REGION, then ask, then default.
resolve_region() {
  local chosen="${REGION_ARG:-${REGION:-}}"

  # Nothing supplied — offer a picker. When this script is piped into bash,
  # stdin is the script text, so the prompt must read from the terminal
  # directly. No terminal (CI, nohup) means fall back to the default.
  if [[ -z "${chosen}" ]]; then
    # Test by opening /dev/tty, not by stat-ing it — the path can be readable
    # on a host where opening it still fails.
    if { exec 3< /dev/tty; } 2>/dev/null; then
      list_regions
      printf '\n  Pick a number, type a region, or press Enter for us-central1: '
      local reply=""
      read -r reply <&3 || true
      exec 3<&-
      if [[ -z "${reply}" ]]; then
        chosen="us-central1"
      elif [[ "${reply}" =~ ^[0-9]+$ ]] \
           && (( reply >= 1 && reply <= ${#GPU_REGIONS[@]} )); then
        chosen="${GPU_REGIONS[$((reply - 1))]}"
      else
        chosen="${reply}"
      fi
    else
      chosen="us-central1"
      printf '\n  No terminal to prompt on — defaulting to us-central1.\n'
      printf '  Pass one explicitly:  ... | bash -s -- %s PROJECT_ID REGION\n' "${CMD}"
    fi
  fi

  if ! is_gpu_region "${chosen}"; then
    printf '\n\033[33m!!  %s is not in the known GPU region list.\033[0m\n' "${chosen}"
    printf '    The model deploy will fail if it has no L4 capacity.\n'
    printf '    Run "regions" to see the list.\n'
  fi

  REGION="${chosen}"
  export REGION
  ok "region ${REGION}"
}

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
  if [[ -z "${PROJECT}" ]]; then
    printf '\n\033[31mError: a Google Cloud project ID is required.\033[0m\n\n' >&2
    printf '  Find yours (the PROJECT_ID column):\n    gcloud projects list\n\n' >&2
    printf '  Or create one (the id must be globally unique):\n' >&2
    printf '    gcloud projects create my-gemma-agent-4f2a1\n\n' >&2
    printf '  Then re-run:\n    ... | bash -s -- %s YOUR_PROJECT_ID\n\n' "${what}" >&2
    exit 1
  fi

  check_prereqs yes

  gcloud projects describe "${PROJECT}" >/dev/null 2>&1 || \
    die "cannot access project '${PROJECT}' — check the id, and run: gcloud auth login"
  ok "project ${PROJECT} reachable"

  # Exported so deploy.sh picks it up — it reads REGION from the environment.
  resolve_region

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
  local)   run_local ;;
  deploy)  run_deploy deploy ;;
  agent)   run_deploy agent ;;
  regions) list_regions ;;
  check)   check_prereqs "${PROJECT:-no}" ;;
  ""|-h|--help|help) usage ;;
  *)       die "unknown command '${CMD}' — try: local, deploy, agent, regions, check" ;;
esac
