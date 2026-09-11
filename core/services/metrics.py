from __future__ import annotations

import os
import resource
import shutil
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock


@dataclass(frozen=True, slots=True)
class MetricSnapshot:
    counters: dict[str, int]
    timings: dict[str, dict[str, float]]
    resources: dict[str, float]


class MetricsService:
    """Zero-dependency bounded runtime metrics; no exporter is required."""

    MAX_NAMES = 256
    MAX_SAMPLES = 256

    def __init__(self, project_root: str | Path) -> None:
        self.project_root = Path(project_root).resolve()
        self._counters: dict[str, int] = defaultdict(int)
        self._samples: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._started = False

    async def start(self) -> None:
        self._started = True

    async def close(self) -> None:
        self._started = False

    def increment(self, name: str, value: int = 1) -> None:
        name = str(name)[:120]
        with self._lock:
            if name not in self._counters and len(self._counters) >= self.MAX_NAMES:
                return
            self._counters[name] += int(value)

    def observe(self, name: str, seconds: float) -> None:
        name = str(name)[:120]
        with self._lock:
            samples = self._samples.get(name)
            if samples is None:
                if len(self._samples) >= self.MAX_NAMES:
                    return
                samples = self._samples[name] = deque(maxlen=self.MAX_SAMPLES)
            samples.append(max(0.0, float(seconds)))

    def timer(self, name: str):
        service = self
        class _Timer:
            def __enter__(self):
                self.started = time.perf_counter()
                return self
            def __exit__(self, exc_type, exc, tb):
                service.observe(name, time.perf_counter() - self.started)
        return _Timer()

    def snapshot(self) -> MetricSnapshot:
        with self._lock:
            counters = dict(self._counters)
            timings: dict[str, dict[str, float]] = {}
            for name, values in self._samples.items():
                if not values:
                    continue
                ordered = sorted(values)
                timings[name] = {
                    "count": float(len(ordered)),
                    "avg_ms": sum(ordered) / len(ordered) * 1000,
                    "p50_ms": ordered[(len(ordered)-1)//2] * 1000,
                    "p95_ms": ordered[min(len(ordered)-1, int(len(ordered)*0.95))] * 1000,
                    "max_ms": ordered[-1] * 1000,
                }
            return MetricSnapshot(counters, timings, self.resources())

    def resources(self) -> dict[str, float]:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        stat = Path("/proc/self/statm")
        rss_bytes = 0.0
        if stat.exists():
            try:
                pages = int(stat.read_text().split()[1])
                rss_bytes = pages * os.sysconf("SC_PAGE_SIZE")
            except (OSError, ValueError, IndexError):
                pass
        try:
            disk = shutil.disk_usage(self.project_root)
            free_bytes = float(disk.free)
        except OSError:
            free_bytes = -1.0
        return {
            "rss_bytes": rss_bytes,
            "user_cpu_seconds": float(usage.ru_utime),
            "system_cpu_seconds": float(usage.ru_stime),
            "disk_free_bytes": free_bytes,
        }
