from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd().resolve()


def check(path: Path):
    text = path.read_text(encoding="utf-8")
    ast.parse(text)
    return {
        "live_import": "src.department3.live_orchestration" in text,
        "guard_import": "src.department3.runtime_guard" in text,
        "bridge": "DEPARTMENT3_PHASE4C_LIVE_BRIDGE" in text,
    }


if __name__ == "__main__":
    for rel in ("app.py", "src/execution/stages.py"):
        p = ROOT / rel
        if not p.is_file():
            raise SystemExit(f"missing {rel}")
        result = check(p)
        print(rel, result)
        if not all(result.values()):
            raise SystemExit(f"Phase 4C live bridge incomplete in {rel}")
    print("Phase 4C live bridge verification: PASS")
