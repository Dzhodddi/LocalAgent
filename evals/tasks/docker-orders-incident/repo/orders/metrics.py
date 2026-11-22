"""Prometheus metrics in the text exposition format, without dependencies."""

import threading
from collections import defaultdict

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

_lock = threading.Lock()
_requests = defaultdict(int)  # (route, status) -> count
_durations = defaultdict(lambda: [0] * (len(BUCKETS) + 1))  # route -> bucket counts (+Inf last)
_sums = defaultdict(float)


def observe(route: str, status: int, seconds: float) -> None:
    with _lock:
        _requests[(route, str(status))] += 1
        for i, bound in enumerate(BUCKETS):
            if seconds <= bound:
                _durations[route][i] += 1
        _durations[route][-1] += 1
        _sums[route] += seconds


def render() -> str:
    lines = ["# TYPE http_requests_total counter"]
    with _lock:
        for (route, status), count in sorted(_requests.items()):
            lines.append(f'http_requests_total{{route="{route}",status="{status}"}} {count}')
        lines.append("# TYPE http_request_duration_seconds histogram")
        for route, counts in sorted(_durations.items()):
            for bound, count in zip(BUCKETS, counts, strict=False):
                lines.append(f'http_request_duration_seconds_bucket{{route="{route}",le="{bound}"}} {count}')
            lines.append(f'http_request_duration_seconds_bucket{{route="{route}",le="+Inf"}} {counts[-1]}')
            lines.append(f'http_request_duration_seconds_sum{{route="{route}"}} {_sums[route]:.4f}')
            lines.append(f'http_request_duration_seconds_count{{route="{route}"}} {counts[-1]}')
    return "\n".join(lines) + "\n"
