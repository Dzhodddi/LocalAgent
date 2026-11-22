On-call alert: the orders API is returning errors in production. It runs in Docker next to
Prometheus. Use the container logs and the metrics to find which requests fail and why,
fix the cause in the code, and add a regression test for the failing input.
