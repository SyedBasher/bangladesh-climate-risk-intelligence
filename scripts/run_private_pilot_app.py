from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clr.private_workspace_pilot_app import serve_private_pilot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the named-user private pilot backend behind a TLS reverse proxy."
    )
    parser.add_argument(
        "--root",
        default=os.getenv("CLR_PRIVATE_DATA", str(ROOT / "private_data")),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--session-minutes", type=int, default=60)
    parser.add_argument(
        "--allow-insecure-cookie",
        action="store_true",
        help="Local test only. Hosted pilot cookies should remain Secure.",
    )
    args = parser.parse_args()
    serve_private_pilot(
        args.root,
        host=args.host,
        port=args.port,
        session_minutes=args.session_minutes,
        secure_cookie=not args.allow_insecure_cookie,
    )


if __name__ == "__main__":
    main()
