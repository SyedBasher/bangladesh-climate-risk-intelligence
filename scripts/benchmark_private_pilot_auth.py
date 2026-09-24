from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_auth_benchmark import benchmark_private_pilot_auth


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the private pilot PBKDF2 cost and calculate a "
            "conservative global login-attempt ceiling for this host."
        )
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--vcpus", type=int, default=2)
    parser.add_argument(
        "--target-cpu-share",
        type=float,
        default=0.10,
        help=(
            "Fraction of total host CPU budget permitted for sustained "
            "unauthenticated password hashing; default 0.10."
        ),
    )
    args = parser.parse_args()
    result = benchmark_private_pilot_auth(
        samples=args.samples,
        vcpus=args.vcpus,
        target_cpu_share=args.target_cpu_share,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
