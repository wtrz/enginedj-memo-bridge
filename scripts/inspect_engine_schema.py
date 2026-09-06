from __future__ import annotations

import argparse
from pathlib import Path

from enginedj_memo_bridge.engine_db import EngineDatabase, default_engine_database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", nargs="?", default=str(default_engine_database()))
    args = parser.parse_args()
    print(EngineDatabase(Path(args.database)).schema_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
