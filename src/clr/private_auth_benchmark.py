from __future__ import annotations

import math
import secrets
import statistics
import time
from typing import Any

from .private_workspace_access import DEFAULT_ITERATIONS, _password_digest


def recommend_global_login_ceiling(
    *,
    median_hash_seconds: float,
    vcpus: int,
    target_cpu_share: float,
) -> int:
    seconds = float(median_hash_seconds)
    cpu_count = int(vcpus)
    share = float(target_cpu_share)
    if seconds <= 0:
        raise ValueError("median_hash_seconds must be positive")
    if cpu_count < 1:
        raise ValueError("vcpus must be at least 1")
    if not 0 < share <= 1:
        raise ValueError("target_cpu_share must be in (0, 1]")
    budget_cpu_seconds_per_minute = 60.0 * cpu_count * share
    return max(
        1,
        math.floor(budget_cpu_seconds_per_minute / seconds),
    )


def benchmark_private_pilot_auth(
    *,
    samples: int = 5,
    iterations: int = DEFAULT_ITERATIONS,
    vcpus: int = 2,
    target_cpu_share: float = 0.10,
) -> dict[str, Any]:
    sample_count = int(samples)
    iteration_count = int(iterations)
    if sample_count < 3 or sample_count > 50:
        raise ValueError("samples must be between 3 and 50")
    if iteration_count < 100_000:
        raise ValueError("iterations must be at least 100000")

    durations: list[float] = []
    password = "synthetic-private-pilot-benchmark"
    for _ in range(sample_count):
        salt = secrets.token_bytes(16)
        start = time.perf_counter()
        _password_digest(password, salt, iteration_count)
        durations.append(time.perf_counter() - start)

    median_seconds = statistics.median(durations)
    recommended = recommend_global_login_ceiling(
        median_hash_seconds=median_seconds,
        vcpus=vcpus,
        target_cpu_share=target_cpu_share,
    )
    return {
        "samples": sample_count,
        "iterations": iteration_count,
        "median_hash_seconds": round(median_seconds, 6),
        "min_hash_seconds": round(min(durations), 6),
        "max_hash_seconds": round(max(durations), 6),
        "vcpus": int(vcpus),
        "target_cpu_share": float(target_cpu_share),
        "recommended_global_attempts_per_minute": recommended,
        "note": (
            "Synthetic benchmark only. Re-run on the deployed host under "
            "representative load before inviting outside pilot users."
        ),
    }
