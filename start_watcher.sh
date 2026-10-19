
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

: "${SEC_USER_AGENT:?Set SEC_USER_AGENT to your application name and contact email}"

export REDIS_URL="${REDIS_URL:-redis://localhost:6380/0}"
export OAF_STREAM="${OAF_STREAM:-secagent.multicompany.v1}"
export SEC_MARKER_PREFIX="${SEC_MARKER_PREFIX:-secagent:multicompany:v1}"

exec .venv/bin/python -m secagent.agents.run_watcher \
    --continuous --interval 300 --limit 2
