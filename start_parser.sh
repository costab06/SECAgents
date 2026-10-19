
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

export REDIS_URL="${REDIS_URL:-redis://localhost:6380/0}"
export OAF_STREAM="${OAF_STREAM:-secagent.multicompany.v1}"
export SEC_ARTIFACT_ROOT="${SEC_ARTIFACT_ROOT:-data/filings}"

exec .venv/bin/python -m secagent.agents.run_parser
