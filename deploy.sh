#!/usr/bin/env bash
#
# Deploy the Gemma 4 agent to Cloud Run.
#
#   ./deploy.sh <PROJECT_ID> model     build + deploy Ollama/Gemma on an L4 GPU  (~25 min, costs money)
#   ./deploy.sh <PROJECT_ID> agent     build + deploy the agent service          (~2 min, ~free)
#   ./deploy.sh <PROJECT_ID> all       model, then agent
#   ./deploy.sh <PROJECT_ID> test      send a real question to the deployed agent
#   ./deploy.sh <PROJECT_ID> urls      print the service URLs
#   ./deploy.sh <PROJECT_ID> warm      pin min-instances=1 before a talk   <-- starts GPU billing
#   ./deploy.sh <PROJECT_ID> down      scale to zero                       <-- stops GPU billing
#   ./deploy.sh <PROJECT_ID> destroy   delete both services entirely
#
# COST: the L4 GPU is roughly $0.70-1.00/hour while an instance is running.
# Scale-to-zero (the default) means you pay only while a request is in flight,
# at the price of a ~60s cold start. `warm` keeps one alive so nothing stalls
# on stage — always run `down` afterwards.
#
set -euo pipefail

PROJECT="${1:-}"
CMD="${2:-}"

REGION="${REGION:-us-central1}"
REPO="${REPO:-gemma}"
MODEL_TAG="${MODEL_TAG:-gemma4}"

MODEL_SVC="gemma-model"
AGENT_SVC="gemma-agent"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bold()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn()  { printf '\033[33m!!  %s\033[0m\n' "$*"; }
money() { printf '\033[31m$$  %s\033[0m\n' "$*"; }

usage() { sed -n '3,20p' "${BASH_SOURCE[0]}"; exit 1; }

[[ -z "${PROJECT}" || -z "${CMD}" ]] && usage

IMG="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"

# ---------------------------------------------------------------- setup

bootstrap() {
  bold "Project ${PROJECT} · region ${REGION}"
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com --project "${PROJECT}" --quiet

  gcloud artifacts repositories describe "${REPO}" \
    --location "${REGION}" --project "${PROJECT}" >/dev/null 2>&1 || {
      bold "Creating Artifact Registry repo '${REPO}'"
      gcloud artifacts repositories create "${REPO}" \
        --repository-format=docker --location="${REGION}" \
        --description="Gemma agent images" --project "${PROJECT}" --quiet
    }
}

model_url() {
  gcloud run services describe "${MODEL_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --format 'value(status.url)' 2>/dev/null || true
}

agent_url() {
  gcloud run services describe "${AGENT_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --format 'value(status.url)' 2>/dev/null || true
}

# ---------------------------------------------------------------- model

deploy_model() {
  bootstrap

  money "About to build an ~11GB GPU image and deploy an L4 (~\$0.70-1.00/hr when running)."
  read -r -p "    Continue? [y/N] " ok
  [[ "${ok}" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

  # The model is baked into the image on purpose. If the container pulled
  # 9.6GB at startup instead, every cold start would be 3-5 minutes.
  bold "Writing build context"
  local tmp="${ROOT}/.build-model"
  rm -rf "${tmp}" && mkdir -p "${tmp}"

  cat > "${tmp}/Dockerfile" <<DOCKER
FROM ollama/ollama:latest
ARG MODEL=${MODEL_TAG}
ENV OLLAMA_HOST=0.0.0.0:8080 \\
    OLLAMA_MODELS=/models \\
    OLLAMA_KEEP_ALIVE=-1 \\
    OLLAMA_NUM_PARALLEL=1
RUN /bin/ollama serve & \\
    pid=\$! ; \\
    until /bin/ollama list >/dev/null 2>&1 ; do sleep 1 ; done ; \\
    /bin/ollama pull "\${MODEL}" ; \\
    /bin/ollama list ; \\
    kill \$pid
ENTRYPOINT []
CMD ["/bin/ollama", "serve"]
DOCKER

  cat > "${tmp}/cloudbuild.yaml" <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build','-t','${IMG}/model:latest','.']
    timeout: 3000s
images: ['${IMG}/model:latest']
options:
  machineType: E2_HIGHCPU_32
  diskSizeGb: 200
timeout: 3600s
YAML

  bold "Building — 20-30 minutes. Safe to leave running."
  gcloud builds submit "${tmp}" --config "${tmp}/cloudbuild.yaml" \
    --project "${PROJECT}" --region "${REGION}"
  rm -rf "${tmp}"

  bold "Deploying ${MODEL_SVC} on 1x NVIDIA L4"
  # --no-cpu-throttling is required for GPU workloads.
  # max-instances 1 caps the blast radius: one GPU, not ten.
  gcloud run deploy "${MODEL_SVC}" \
    --image "${IMG}/model:latest" \
    --region "${REGION}" --project "${PROJECT}" \
    --port 8080 --cpu 8 --memory 32Gi \
    --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy \
    --no-cpu-throttling --execution-environment gen2 \
    --max-instances 1 --min-instances 0 \
    --concurrency 4 --timeout 600 \
    --allow-unauthenticated --quiet

  bold "Model service: $(model_url)"
  warn "It is public. Delete it after the workshop: ./deploy.sh ${PROJECT} destroy"
}

# ---------------------------------------------------------------- agent

deploy_agent() {
  bootstrap

  local url="${LLM_BASE_URL:-}"
  if [[ -z "${url}" ]]; then
    local m; m="$(model_url)"
    [[ -n "${m}" ]] && url="${m}/v1"
  fi
  if [[ -z "${url}" ]]; then
    warn "No model service found and LLM_BASE_URL not set."
    warn "Either deploy the model first, or point at an existing endpoint:"
    warn "  LLM_BASE_URL=https://your-ollama.run.app/v1 ./deploy.sh ${PROJECT} agent"
    exit 1
  fi
  bold "Agent will call ${url}"

  # --source builds with buildpacks; no Dockerfile needed for this service.
  gcloud run deploy "${AGENT_SVC}" \
    --source "${ROOT}" \
    --region "${REGION}" --project "${PROJECT}" \
    --port 8080 --cpu 1 --memory 512Mi \
    --max-instances 5 --min-instances 0 \
    --concurrency 20 --timeout 600 \
    --allow-unauthenticated \
    --set-env-vars "LLM_BASE_URL=${url},MODEL=${MODEL_TAG},MAX_STEPS=6" \
    --quiet

  bold "Agent service: $(agent_url)"
}

# ---------------------------------------------------------------- ops

do_test() {
  local a; a="$(agent_url)"
  [[ -z "${a}" ]] && { warn "Agent not deployed."; exit 1; }

  bold "Health"
  curl -s "${a}/healthz" ; echo

  bold "Asking a question that needs two chained tools"
  warn "First call may take ~60s if the GPU is cold."
  curl -s -X POST "${a}/chat" -H 'Content-Type: application/json' \
    -d '{"message":"What is the temperature in Lagos right now, and what is that in Fahrenheit?"}' ; echo

  bold "Usage metrics"
  curl -s "${a}/metrics" ; echo
}

do_warm() {
  bold "Pinning min-instances=1 — run this ~20 min before you present"
  gcloud run services update "${MODEL_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --min-instances 1 --quiet
  gcloud run services update "${AGENT_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --min-instances 1 --quiet
  money "GPU billing has started (~\$0.70-1.00/hr)."
  money "When you are done:  ./deploy.sh ${PROJECT} down"
}

do_down() {
  bold "Scaling both services to zero"
  gcloud run services update "${MODEL_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --min-instances 0 --quiet 2>/dev/null || true
  gcloud run services update "${AGENT_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --min-instances 0 --quiet 2>/dev/null || true
  bold "Idle GPU billing stopped. Services still exist; 'destroy' removes them."
}

do_destroy() {
  warn "This deletes ${MODEL_SVC} and ${AGENT_SVC} from ${PROJECT}."
  read -r -p "    Type the project id to confirm: " typed
  [[ "${typed}" == "${PROJECT}" ]] || { echo "Mismatch. Nothing deleted."; exit 1; }
  gcloud run services delete "${MODEL_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --quiet 2>/dev/null || true
  gcloud run services delete "${AGENT_SVC}" --region "${REGION}" \
    --project "${PROJECT}" --quiet 2>/dev/null || true
  bold "Deleted. The 11GB image is still in Artifact Registry (~\$1/month)."
  echo "    Remove it too:  gcloud artifacts repositories delete ${REPO} --location ${REGION} --project ${PROJECT}"
}

case "${CMD}" in
  model)   deploy_model ;;
  agent)   deploy_agent ;;
  all)     deploy_model && deploy_agent ;;
  test)    do_test ;;
  urls)    echo "model: $(model_url)"; echo "agent: $(agent_url)" ;;
  warm)    do_warm ;;
  down)    do_down ;;
  destroy) do_destroy ;;
  *)       usage ;;
esac
