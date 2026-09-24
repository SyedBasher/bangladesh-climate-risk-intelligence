from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_workspace_app import serve_private_workspace


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the local authenticated private climate intelligence workspace."
    )
    parser.add_argument(
        "--root",
        default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--session-minutes", type=int, default=60)
    parser.add_argument(
        "--allow-legacy-shared-password",
        action="store_true",
        help=(
            "Explicit local-only opt-in. Never use this legacy shell for the "
            "hosted private pilot."
        ),
    )
    args = parser.parse_args()
    serve_private_workspace(
        args.root,
        host=args.host,
        port=args.port,
        session_ttl=args.session_minutes * 60,
        allow_legacy_shared_password=args.allow_legacy_shared_password,
    )


if __name__ == "__main__":
    main()
