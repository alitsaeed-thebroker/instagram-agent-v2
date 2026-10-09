from __future__ import annotations

import ast
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.cwd().resolve()
TARGETS = [
    ROOT / "app.py",
    ROOT / "src" / "execution" / "stages.py",
]
BACKUP_ROOT = ROOT / "output" / "backups" / "department3-phase4c1"

IMPORTS = [
    "from src.department3.live_orchestration import LiveDepartment3Orchestrator, quarantine_legacy_result\n",
    "from src.department3.runtime_guard import assert_noncanonical_output\n",
]

MARKER = "# DEPARTMENT3_PHASE4C_LIVE_BRIDGE"

BRIDGE = r