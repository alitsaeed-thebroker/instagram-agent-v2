from __future__ import annotations

import argparse
import json
import os
import sys
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

LEGACY_CANDIDATES = {
    "src/ai/agents/campaign_planner.py",
    "src/ai/agents/content_planner.py",
    "src/ai/agents/creative_director_agent.py",
    "src/ai/agents/marketing_strategy_agent.py",
    "src/ai/agents/visual_art_director_agent.py",
    "src/campaign_intelligence/engine.py",
    "src/creative_intelligence/engine.py",
    "src/planning/engine.py",
}

CANONICAL_D3 = {
    "src/creative/visual_art_director.py",
    "src/creative/visual_direction.py",
    "src/creative/production_contract.py",
}

D4_BOUNDARY = {
    "src/branding/composer.py",
    "src/image_processing/planner.py",
    "src/image_processing/schema.py",
    "src/image_prompts/generator.py",
    "src/production/workflow.py",
}

AUTHORITATIVE_OUTPUT_HINTS = (
    "content-plan",
    "campaign",
    "creative-direction",
    "visual-direction",
    "visual-history",
    "branded",
    "production",
    "post-package",
    "review",
    "strategy",
)

DEFAULT_TEST_TARGETS = [
    "tests/test_visual_art_director.py",
    "tests/test_vdc_branded_qa.py",
    "tests/test_department4_production_contract.py",
    "tests/test_brand_composer.py",
    "tests/test_image_processing_planner.py",
    "tests/test_image_prompt_generator.py",
    "tests/test_instagram_story_support.py",
    "tests/test_real_estate_creative_intelligence.py",
    "tests/test_real_estate_creative_reviewer.py",
    "tests/test_campaign_intelligence.py",
    "tests/test_content_planner.py",
    "tests/test_creative_director_agent.py",
    "tests/test_marketing_strategy_agent.py",
]


@dataclass
class CallEvent:
    seq: int
    ts_ns: int
    file: str
    function: str
    line: int
    caller_file: str | None
    caller_function: str | None
    category: str


@dataclass
class IOEvent:
    seq: int
    ts_ns: int
    operation: str
    path: str
    mode: str | None
    caller_file: str | None
    caller_function: str | None
    category: str
    authoritative_hint: bool


class RuntimeAuthorityTracer:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.call_events: list[CallEvent] = []
        self.io_events: list[IOEvent] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._started = False
        self._old_profile = None
        self._old_thread_profile = None

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def rel(self, filename: str | os.PathLike[str] | None) -> str | None:
        if not filename:
            return None
        try:
            p = Path(filename).resolve()
            return p.relative_to(self.repo).as_posix()
        except Exception:
            return None

    def category(self, relpath: str | None) -> str:
        if relpath in CANONICAL_D3:
            return "CANONICAL_D3"
        if relpath in LEGACY_CANDIDATES:
            return "LEGACY_CANDIDATE"
        if relpath in D4_BOUNDARY:
            return "D4_BOUNDARY"
        if relpath and relpath.startswith("src/"):
            return "OTHER_SRC"
        if relpath and relpath.startswith("tests/"):
            return "TEST"
        return "OTHER"

    def profile(self, frame, event, arg):
        if event != "call":
            return self.profile
        relpath = self.rel(frame.f_code.co_filename)
        if relpath not in LEGACY_CANDIDATES | CANONICAL_D3 | D4_BOUNDARY:
            return self.profile

        caller = frame.f_back
        caller_file = self.rel(caller.f_code.co_filename) if caller else None
        caller_fn = caller.f_code.co_name if caller else None

        self.call_events.append(CallEvent(
            seq=self._next_seq(),
            ts_ns=time.time_ns(),
            file=relpath,
            function=frame.f_code.co_name,
            line=frame.f_lineno,
            caller_file=caller_file,
            caller_function=caller_fn,
            category=self.category(relpath),
        ))
        return self.profile

    def audit_hook(self, event: str, args: tuple[Any, ...]):
        if event != "open":
            return
        if not args:
            return

        raw = args[0]
        if isinstance(raw, int):
            return
        try:
            p = Path(raw)
        except Exception:
            return

        try:
            resolved = p.resolve()
            relpath = resolved.relative_to(self.repo).as_posix()
        except Exception:
            return

        mode = None
        if len(args) > 1 and isinstance(args[1], str):
            mode = args[1]

        operation = "read"
        if mode and any(flag in mode for flag in ("w", "a", "x", "+")):
            operation = "write"

        caller_file = caller_function = None
        try:
            frame = sys._getframe(1)
            for _ in range(12):
                relcaller = self.rel(frame.f_code.co_filename)
                if relcaller and not relcaller.startswith("tools/department3_phase3_runtime_authority_trace.py"):
                    caller_file = relcaller
                    caller_function = frame.f_code.co_name
                    break
                frame = frame.f_back
                if frame is None:
                    break
        except Exception:
            pass

        low = relpath.casefold()
        authoritative = any(h in low for h in AUTHORITATIVE_OUTPUT_HINTS)
        self.io_events.append(IOEvent(
            seq=self._next_seq(),
            ts_ns=time.time_ns(),
            operation=operation,
            path=relpath,
            mode=mode,
            caller_file=caller_file,
            caller_function=caller_function,
            category=self.category(caller_file),
            authoritative_hint=authoritative,
        ))

    def start(self):
        if self._started:
            return
        self._started = True
        self._old_profile = sys.getprofile()
        self._old_thread_profile = threading.getprofile()
        sys.addaudithook(self.audit_hook)
        sys.setprofile(self.profile)
        threading.setprofile(self.profile)

    def stop(self):
        if not self._started:
            return
        sys.setprofile(self._old_profile)
        threading.setprofile(self._old_thread_profile)
        self._started = False


def run_pytest_in_process(repo: Path, targets: list[str]) -> dict[str, Any]:
    import pytest

    existing = [t for t in targets if (repo / t).is_file()]
    if not existing:
        return {
            "ran": False,
            "returncode": None,
            "targets": [],
            "reason": "No requested test targets exist.",
        }

    args = ["-q", *existing]
    code = pytest.main(args)
    return {
        "ran": True,
        "returncode": int(code),
        "targets": existing,
        "args": args,
    }


def aggregate_calls(events: list[CallEvent]) -> dict[str, Any]:
    per_file: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str, str], int] = defaultdict(int)

    for e in events:
        slot = per_file.setdefault(e.file, {
            "category": e.category,
            "calls": 0,
            "functions": defaultdict(int),
            "callers": defaultdict(int),
        })
        slot["calls"] += 1
        slot["functions"][e.function] += 1
        if e.caller_file:
            slot["callers"][f"{e.caller_file}::{e.caller_function}"] += 1
            edges[(e.caller_file, e.caller_function or "", e.file, e.function)] += 1

    clean = {}
    for file, data in sorted(per_file.items()):
        clean[file] = {
            "category": data["category"],
            "calls": data["calls"],
            "functions": dict(sorted(data["functions"].items(), key=lambda x: (-x[1], x[0]))),
            "callers": dict(sorted(data["callers"].items(), key=lambda x: (-x[1], x[0]))),
        }

    edge_list = [
        {
            "caller_file": a,
            "caller_function": b,
            "callee_file": c,
            "callee_function": d,
            "count": n,
        }
        for (a, b, c, d), n in sorted(edges.items(), key=lambda x: (-x[1], x[0]))
    ]

    return {"per_file": clean, "edges": edge_list}


def aggregate_io(events: list[IOEvent]) -> dict[str, Any]:
    writers: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    readers: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    authoritative_writes = []

    for e in events:
        who = f"{e.caller_file}::{e.caller_function}" if e.caller_file else "<unknown>"
        if e.operation == "write":
            writers[e.path][who] += 1
            if e.authoritative_hint:
                authoritative_writes.append(asdict(e))
        else:
            readers[e.path][who] += 1

    return {
        "writers": {
            p: dict(sorted(v.items(), key=lambda x: (-x[1], x[0])))
            for p, v in sorted(writers.items())
        },
        "readers": {
            p: dict(sorted(v.items(), key=lambda x: (-x[1], x[0])))
            for p, v in sorted(readers.items())
        },
        "authoritative_write_events": authoritative_writes,
    }


def classify_runtime_authority(call_summary: dict[str, Any], io_summary: dict[str, Any]) -> dict[str, Any]:
    per_file = call_summary["per_file"]
    authoritative_writes = io_summary["authoritative_write_events"]

    result = {}
    for file in sorted(LEGACY_CANDIDATES | CANONICAL_D3 | D4_BOUNDARY):
        executed = file in per_file
        writes = [
            w for w in authoritative_writes
            if w.get("caller_file") == file
        ]

        if file in LEGACY_CANDIDATES:
            if not executed:
                status = "NOT_EXECUTED_IN_TRACED_SUITE"
                severity = "INFO"
            elif writes:
                status = "EXECUTED_AND_WRITES_AUTHORITATIVE_LOOKING_STATE"
                severity = "HIGH"
            else:
                status = "EXECUTED_NO_AUTHORITATIVE_WRITE_OBSERVED"
                severity = "MEDIUM"
        elif file in CANONICAL_D3:
            if not executed:
                status = "CANONICAL_NOT_EXECUTED_IN_TRACED_SUITE"
                severity = "MEDIUM"
            else:
                status = "CANONICAL_EXECUTED"
                severity = "INFO"
        else:
            if not executed:
                status = "D4_NOT_EXECUTED_IN_TRACED_SUITE"
                severity = "INFO"
            elif writes:
                status = "D4_EXECUTED_WITH_OUTPUT_WRITES"
                severity = "INFO"
            else:
                status = "D4_EXECUTED"
                severity = "INFO"

        result[file] = {
            "category": (
                "LEGACY_CANDIDATE" if file in LEGACY_CANDIDATES
                else "CANONICAL_D3" if file in CANONICAL_D3
                else "D4_BOUNDARY"
            ),
            "executed": executed,
            "runtime_calls": per_file.get(file, {}).get("calls", 0),
            "functions": per_file.get(file, {}).get("functions", {}),
            "authoritative_write_events": writes,
            "status": status,
            "severity": severity,
        }
    return result


def make_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Department 3 — Phase 3 Runtime Authority Trace",
        "",
        "This phase is runtime-observation only. Production source is not modified.",
        "",
        "## Test Execution",
        f"- Ran: `{report['pytest']['ran']}`",
        f"- Return code: `{report['pytest']['returncode']}`",
        f"- Targets: **{len(report['pytest']['targets'])}**",
        "",
        "## Runtime Authority Classification",
    ]

    for file, info in report["runtime_authority"].items():
        lines.append(
            f"- **{info['severity']}** `{file}` — {info['status']} "
            f"(calls={info['runtime_calls']})"
        )

    lines += ["", "## Runtime Call Edges"]
    for e in report["calls"]["edges"][:200]:
        lines.append(
            f"- `{e['caller_file']}::{e['caller_function']}` → "
            f"`{e['callee_file']}::{e['callee_function']}` × {e['count']}"
        )

    lines += ["", "## Authoritative-Looking Write Events"]
    writes = report["io"]["authoritative_write_events"]
    if not writes:
        lines.append("- None observed.")
    else:
        for w in writes[:300]:
            lines.append(
                f"- `{w.get('caller_file')}::{w.get('caller_function')}` "
                f"→ `{w['path']}` mode=`{w.get('mode')}`"
            )

    lines += ["", "## Decision Rule"]
    lines.append(
        "A legacy candidate is not a confirmed defect merely because it executes. "
        "Modification is justified only when runtime evidence shows it independently writes or "
        "controls an authoritative downstream artifact, or a targeted behavioral test proves it "
        "can bypass the canonical Visual Art Director/VDC authority chain."
    )
    return "\n".join(lines) + "\n"


def run(repo: Path, output_dir: Path, targets: list[str] | None = None) -> dict[str, Any]:
    repo = repo.resolve()
    output_dir = output_dir.resolve()

    if not (repo / "app.py").is_file():
        raise SystemExit("Run from the instagram-agent repository root.")

    tracer = RuntimeAuthorityTracer(repo)
    tracer.start()
    try:
        pytest_result = run_pytest_in_process(repo, targets or DEFAULT_TEST_TARGETS)
    finally:
        tracer.stop()

    calls = aggregate_calls(tracer.call_events)
    io = aggregate_io(tracer.io_events)
    runtime_authority = classify_runtime_authority(calls, io)

    report = {
        "schema_version": "department3.phase3.runtime_authority_trace.v1",
        "repository": str(repo),
        "pytest": pytest_result,
        "summary": {
            "call_events": len(tracer.call_events),
            "io_events": len(tracer.io_events),
            "executed_legacy_candidates": sum(
                1 for f in LEGACY_CANDIDATES if runtime_authority[f]["executed"]
            ),
            "legacy_candidates_with_authoritative_writes": sum(
                1
                for f in LEGACY_CANDIDATES
                if runtime_authority[f]["authoritative_write_events"]
            ),
            "executed_canonical_d3_files": sum(
                1 for f in CANONICAL_D3 if runtime_authority[f]["executed"]
            ),
            "executed_d4_boundary_files": sum(
                1 for f in D4_BOUNDARY if runtime_authority[f]["executed"]
            ),
            "targeted_tests_pass": pytest_result.get("returncode") == 0
            if pytest_result.get("ran")
            else None,
        },
        "runtime_authority": runtime_authority,
        "calls": calls,
        "io": io,
        "raw_call_events": [asdict(x) for x in tracer.call_events],
        "raw_io_events": [asdict(x) for x in tracer.io_events],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "department3-phase3-runtime-authority-trace.json"
    md_path = output_dir / "department3-phase3-runtime-authority-trace.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(make_markdown(report), encoding="utf-8")

    print("Department 3 Phase 3 runtime authority trace completed")
    print(f"- Call events: {report['summary']['call_events']}")
    print(f"- I/O events: {report['summary']['io_events']}")
    print(f"- Executed legacy candidates: {report['summary']['executed_legacy_candidates']}")
    print(
        "- Legacy candidates with authoritative-looking writes: "
        f"{report['summary']['legacy_candidates_with_authoritative_writes']}"
    )
    print(f"- Executed canonical D3 files: {report['summary']['executed_canonical_d3_files']}")
    print(f"- Executed D4 boundary files: {report['summary']['executed_d4_boundary_files']}")
    print(f"- Targeted tests pass: {report['summary']['targeted_tests_pass']}")
    print(f"- JSON: {json_path}")
    print(f"- Markdown: {md_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--output", default="output/audits/department3")
    parser.add_argument(
        "--tests",
        nargs="*",
        help="Optional explicit pytest target list. Defaults to Department 3/VDC/D4 boundary suite.",
    )
    args = parser.parse_args()
    run(Path(args.repo), Path(args.output), args.tests)


if __name__ == "__main__":
    main()
