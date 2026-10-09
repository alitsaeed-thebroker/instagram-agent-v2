"""Install Phase 1.1 — bounded Marketing Strategy context.

Run from the root of ``instagram-agent V2`` after extracting this package into
that folder. The installer verifies the baseline, backs up each changed file,
installs the bounded source-truth strategy brief, bumps the strategy cache
version, compiles the changes, and runs focused tests. It makes no API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


BASELINE_AGENT_SHA256 = "f28e28c9c777cd8fc5f30a90165e39c991f44ca90c048f8f5a08ab5d8afcec82"
PATCHED_AGENT_SHA256 = "0ad6b893a3fa6682582f28b7167da79d4abe3c804593432c88094b2de714c441"
BASELINE_TEST_SHA256 = "3f4440c34b9e973f51bd99c5dfd5722c510bb9bcb8b8a2e7792a83c8ef0fcdcd"
PATCHED_TEST_SHA256 = "90ad2573096a5d9defa728b977f690298431e2605c078917a37ce4127c30a11e"
OLD_CACHE_MARKER = 'module_version="1.2.0",model_policy=os.getenv("OPENAI_MODEL","gpt-4o-mini")'
NEW_CACHE_MARKER = 'module_version="1.3.0",model_policy=os.getenv("OPENAI_MODEL","gpt-4o-mini")'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _backup_once(path: Path, suffix: str) -> Path:
    backup = path.with_name(path.name + suffix)
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"Backup created: {backup.name}")
    else:
        print(f"Existing backup preserved: {backup.name}")
    return backup


def install(project_root: Path) -> int:
    root = project_root.resolve()
    package_root = Path(__file__).resolve().parent
    payload_root = package_root / "phase1_marketing_strategy_context_fix_payload"

    agent = root / "src" / "ai" / "agents" / "marketing_strategy_agent.py"
    test = root / "tests" / "test_marketing_strategy_agent.py"
    app = root / "app.py"
    payload_agent = payload_root / "src" / "ai" / "agents" / "marketing_strategy_agent.py"
    payload_test = payload_root / "tests" / "test_marketing_strategy_agent.py"

    for path in (agent, test, app, payload_agent, payload_test):
        if not path.is_file():
            print(f"ERROR: Required file is missing: {path}")
            return 1

    agent_hash = _sha256(agent)
    test_hash = _sha256(test)
    if agent_hash not in {BASELINE_AGENT_SHA256, PATCHED_AGENT_SHA256}:
        print("ERROR: MarketingStrategyAgent differs from the certified Phase 1 baseline.")
        return 1
    if test_hash not in {BASELINE_TEST_SHA256, PATCHED_TEST_SHA256}:
        print("ERROR: MarketingStrategyAgent tests differ from the certified Phase 1 baseline.")
        return 1
    if _sha256(payload_agent) != PATCHED_AGENT_SHA256 or _sha256(payload_test) != PATCHED_TEST_SHA256:
        print("ERROR: Installer payload integrity check failed.")
        return 1

    app_text = app.read_text(encoding="utf-8-sig")
    old_count = app_text.count(OLD_CACHE_MARKER)
    new_count = app_text.count(NEW_CACHE_MARKER)
    if not ((old_count == 1 and new_count == 0) or (old_count == 0 and new_count == 1)):
        print("ERROR: app.py marketing-strategy cache marker is missing or ambiguous.")
        return 1

    if agent_hash != PATCHED_AGENT_SHA256:
        _backup_once(agent, ".phase1_context_backup")
        shutil.copy2(payload_agent, agent)
        print("Bounded MarketingStrategyAgent installed.")
    else:
        print("Bounded MarketingStrategyAgent is already installed.")

    if test_hash != PATCHED_TEST_SHA256:
        _backup_once(test, ".phase1_context_backup")
        shutil.copy2(payload_test, test)
        print("Marketing strategy context tests installed.")

    if old_count == 1:
        _backup_once(app, ".phase1_context_backup")
        updated = app_text.replace(OLD_CACHE_MARKER, NEW_CACHE_MARKER, 1)
        compile(updated, str(app), "exec")
        app.write_text(updated, encoding="utf-8")
        print("Marketing-strategy cache version updated to 1.3.0.")
    else:
        print("Marketing-strategy cache version is already 1.3.0.")

    py_compile.compile(str(agent), doraise=True)
    py_compile.compile(str(test), doraise=True)
    py_compile.compile(str(app), doraise=True)
    print("Python syntax verification: PASS")

    command = [
        sys.executable,
        "-m",
        "unittest",
        "tests.test_marketing_strategy_agent",
        "tests.test_department3_phase4d2_entrypoint",
        "tests.test_department3_phase4d0_capture",
    ]
    completed = subprocess.run(command, cwd=root, check=False)
    if completed.returncode != 0:
        print("ERROR: Focused Marketing Strategy verification failed.")
        return completed.returncode

    print("Focused Marketing Strategy verification: PASS")
    print("Maximum advisory input: 90000 characters")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install the bounded Marketing Strategy context repair."
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
