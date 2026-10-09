from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path.cwd().resolve()
MARKER = "# DEPARTMENT3_PHASE4C_LIVE_BRIDGE"

def verify(rel: str) -> dict:
    path = ROOT / rel
    if not path.is_file():
        raise SystemExit(f"Missing: {rel}")
    text = path.read_text(encoding="utf-8")
    ast.parse(text, filename=str(path))
    result = {
        "live_import": "from src.department3.live_orchestration import" in text,
        "guard_import": "from src.department3.runtime_guard import" in text,
        "bridge": MARKER in text,
        "bridge_function": "def _department3_canonical_approve(" in text,
    }
    print(rel, result)
    if not all(result.values()):
        raise SystemExit(f"FAIL: {rel}")
    return result

if __name__ == "__main__":
    verify("app.py")
    verify("src/execution/stages.py")
    print("Phase 4C.2 verification: PASS")
