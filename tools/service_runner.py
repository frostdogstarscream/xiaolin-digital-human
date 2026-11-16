"""Entry point for both source deployments and the frozen Windows service."""
import argparse
import multiprocessing
import sys
import os
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--data-dir", help="Explicit isolated data directory for testing or deployment")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["AVATAR_DATA_DIR"] = str(Path(args.data_dir).resolve())
    import uvicorn
    from service.app import app as kiosk
    from service.demo import app as demo
    uvicorn.run(demo if args.demo else kiosk, host="127.0.0.1", port=args.port or (8766 if args.demo else 8765),
                access_log=False, log_level="warning", ws_max_size=4 * 1024 * 1024)


if __name__ == "__main__":
    main()
