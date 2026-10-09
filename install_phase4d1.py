from __future__ import annotations

import ast
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd().resolve()
APP = ROOT / "app.py"
BACKUP = ROOT / "output" / "backups" / "department3-phase4d1"

OLD = 'products = PlanningEngine().run(knowledge, strategy, inventory, paths["opportunities"], creative_intelligence_path=reci, campaign_intelligence_path=campaign_intelligence, write_campaign=stage == "campaign-planner", platform_strategy=_PLATFORM_STRATEGY)'

NEW_LINES = [
    'products = cutover_legacy_planning_products(',
    '                        project_id=project.name,',
    '                        planning_engine=PlanningEngine(),',
    '                        planning_args=(knowledge, strategy, inventory, paths["opportunities"]),',
    '                        planning_kwargs={',
    '                            "creative_intelligence_path": reci,',
    '                            "campaign_intelligence_path": campaign_intelligence,',
    '                            "write_campaign": stage == "campaign-planner",',
    '                            "platform_strategy": _PLATFORM_STRATEGY,',
    '                        },',
    '                    )',
]
NEW = "\n".join(NEW_LINES)

IMPORT = "from src.department3.planning_cutover import cutover_legacy_planning_products\n"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def insert_import(text: str) -> str:
    if IMPORT.strip() in text:
        return text
    tree = ast.parse(text)
    lines = text.splitlines(True)
    index = 0
    if tree.body:
        first = tree.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            index = getattr(first, "end_lineno", first.lineno)
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith("from __future__ import"):
            index += 1
            continue
        break
    lines[index:index] = [IMPORT, "\n"]
    return "".join(lines)


def main() -> None:
    if not APP.is_file():
        raise SystemExit("Run from the instagram-agent repository root.")
    required = ROOT / "src" / "department3" / "planning_cutover.py"
    if not required.is_file():
        raise SystemExit("Missing src/department3/planning_cutover.py")

    parse(APP)
    before = APP.read_text(encoding="utf-8")
    count = before.count(OLD)
    if count != 1:
        raise SystemExit(
            f"Refusing Phase 4D.1 patch: expected exactly one live PlanningEngine authority call, found {count}. No files changed."
        )

    after = insert_import(before).replace(OLD, NEW, 1)

    BACKUP.mkdir(parents=True, exist_ok=True)
    backup = BACKUP / "app.py"
    shutil.copy2(APP, backup)

    APP.write_text(after, encoding="utf-8")
    try:
        parse(APP)
    except Exception:
        shutil.copy2(backup, APP)
        raise

    live = APP.read_text(encoding="utf-8")
    if OLD in live or "cutover_legacy_planning_products(" not in live:
        shutil.copy2(backup, APP)
        raise SystemExit("Canonical cutover verification failed; rolled back.")

    manifest = {
        "schema_version": "department3.phase4d1.canonical_planning_cutover.v1",
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "app_before_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
        "app_after_sha256": sha(APP),
        "backup": str(backup),
    }
    (BACKUP / "install-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Department 3 Phase 4D.1 canonical planning authority cutover: PASS")
    print("- Replaced live PlanningEngine authority call: 1")
    print("- PlanningEngine retained only as compatibility candidate generator")
    print("- Canonical approval now required before planning artifacts continue downstream")
    print(f"- Backup: {backup}")


if __name__ == "__main__":
    main()
