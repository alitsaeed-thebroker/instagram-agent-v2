\
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.department1 import Department1Pipeline


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run canonical Department 1: "
            "INPUT -> READ -> UNDERSTAND -> ANALYZE -> CLASSIFY -> EXTRACT"
        )
    )
    parser.add_argument(
        "--project-root",
        required=True,
        help="Project source folder, e.g. input/Beverly Hills",
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="Optional canonical project name. Defaults to folder name.",
    )
    parser.add_argument(
        "--output-root",
        default="output/department1",
        help="Department 1 output root.",
    )
    args = parser.parse_args()

    handoff = Department1Pipeline(
        Path(args.project_root),
        project_name=args.project_name,
        output_root=args.output_root,
    ).run()

    print(json.dumps({
        "status": "PASS",
        "project": handoff["project"],
        "contract_version": handoff["contract_version"],
        "handoff_sha256": handoff["handoff_sha256"],
        "handoff": str(
            Path(args.output_root)
            / handoff["project_slug"]
            / "department2-handoff.json"
        ),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
