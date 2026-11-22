set -uo pipefail
docker compose -p "$EVAL_RUN_ID" down -v --rmi local --remove-orphans --timeout 2 >/dev/null 2>&1
