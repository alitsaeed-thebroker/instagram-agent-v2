"""Install the Phase 1.0.1 early-.env-loader repair.

Run this script from the root of ``instagram-agent V2``. It creates a backup
of app.py, inserts an early dotenv load before project modules are imported,
and validates the resulting Python source. It never prints credential values.
"""

from __future__ import annotations

import argparse
import codecs
import py_compile
import shutil
import sys
from pathlib import Path

PATCH_SENTINEL = 'load_dotenv(Path(__file__).resolve().parent / ".env")'
PATCH_BLOCK = f'''from pathlib import Path
from dotenv import load_dotenv

{PATCH_SENTINEL}
'''
FUTURE_IMPORT = "from __future__ import annotations"
BACKUP_NAME = "app.py.phase1_env_loader_backup"


def _configured_api_key_exists(env_path: Path) -> bool:
    """Check key presence without importing dotenv or exposing its value."""
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if separator and name.strip() == "OPENAI_API_KEY":
            return bool(value.strip().strip("'\""))
    return False


def install(project_root: Path) -> int:
    root = project_root.resolve()
    app_path = root / "app.py"
    env_path = root / ".env"
    backup_path = root / BACKUP_NAME

    if not app_path.is_file():
        print(f"ERROR: app.py was not found in {root}")
        return 1
    if not env_path.is_file():
        print(f"ERROR: .env was not found in {root}")
        return 1

    if not _configured_api_key_exists(env_path):
        print("ERROR: OPENAI_API_KEY is missing or empty in .env")
        return 1

    raw_source = app_path.read_bytes()
    has_utf8_bom = raw_source.startswith(codecs.BOM_UTF8)
    source = raw_source.decode("utf-8-sig")
    if PATCH_SENTINEL in source:
        compile(source, str(app_path), "exec")
        print("Phase 1.0.1 environment loader is already installed.")
        print("OPENAI_API_KEY status: CONFIGURED")
        return 0

    marker_index = source.find(FUTURE_IMPORT)
    if marker_index < 0:
        print("ERROR: app.py does not contain the expected future import marker.")
        return 1

    newline = "\r\n" if "\r\n" in source else "\n"
    insertion_point = marker_index + len(FUTURE_IMPORT)
    patch_block = PATCH_BLOCK.replace("\n", newline)
    updated = (
        source[:insertion_point]
        + newline
        + newline
        + patch_block
        + source[insertion_point:]
    )
    compile(updated, str(app_path), "exec")

    if not backup_path.exists():
        shutil.copy2(app_path, backup_path)
        print(f"Backup created: {backup_path.name}")
    else:
        print(f"Existing backup preserved: {backup_path.name}")

    encoded = updated.encode("utf-8")
    if has_utf8_bom:
        encoded = codecs.BOM_UTF8 + encoded
    app_path.write_bytes(encoded)
    py_compile.compile(str(app_path), doraise=True)

    print("Phase 1.0.1 environment loader installed successfully.")
    print("OPENAI_API_KEY status: CONFIGURED")
    print("app.py syntax verification: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the Phase 1.0.1 early-.env-loader repair."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Instagram-agent root; defaults to the current directory.",
    )
    return install(parser.parse_args().project_root)


if __name__ == "__main__":
    raise SystemExit(main())
