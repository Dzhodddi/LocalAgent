# Start the incident: build the buggy service from the agent's starting code, start traffic
# and Prometheus, and wait until the errors are in the logs and the metrics.
set -euo pipefail
docker compose -p "$EVAL_RUN_ID" up -d --build --wait orders prometheus >/dev/null
docker compose -p "$EVAL_RUN_ID" up -d traffic >/dev/null
for _ in $(seq 60); do
    if docker compose -p "$EVAL_RUN_ID" logs orders 2>/dev/null | grep -q "Traceback"; then break; fi
    sleep 1
done
sleep 25  # a few Prometheus scrapes
