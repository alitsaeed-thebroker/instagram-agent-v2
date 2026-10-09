from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

CREATIVE_FIELDS = {
    "headline", "cta", "layout", "template", "preset", "crop", "composition",
    "hierarchy", "marketing_objective", "marketing objective", "visual_direction",
    "visual direction", "logo_treatment", "safe_area", "safe area",
}

EXECUTION_VERBS = {
    "render", "draw", "resize", "scale", "measure", "position", "place", "compose",
    "apply", "load", "validate", "verify", "serialize", "deserialize", "save",
    "write", "read", "hash", "sign", "check", "transform", "convert",
}

DECISION_VERBS = {
    "choose", "select", "decide", "recommend", "infer", "derive", "fallback",
    "default", "random", "pick", "suggest", "generate", "plan", "strategy",
}

CANONICAL_D3_FILES = {
    "src/creative/visual_art_director.py",
    "src/creative/visual_direction.py",
    "src/creative/production_contract.py",
}

LEGACY_AUTHORITY_CANDIDATES = {
    "src/ai/agents/campaign_planner.py",
    "src/ai/agents/content_planner.py",
    "src/ai/agents/creative_director_agent.py",
    "src/ai/agents/marketing_strategy_agent.py",
    "src/ai/agents/visual_art_director_agent.py",
    "src/campaign_intelligence/engine.py",
    "src/creative_intelligence/engine.py",
    "src/planning/engine.py",
}

D4_FILES = {
    "src/branding/composer.py",
    "src/image_processing/planner.py",
    "src/image_processing/schema.py",
    "src/image_prompts/generator.py",
    "src/production/workflow.py",
}


@dataclass
class Classification:
    file: str
    line: int
    symbol: str
    finding_code: str
    term: str
    classification: str
    confidence: str
    reason: str
    evidence: list[str]
    action: str


class SourceIndex:
    def __init__(self, repo: Path):
        self.repo = repo
        self.cache: dict[str, dict[str, Any]] = {}

    def get(self, relpath: str) -> dict[str, Any] | None:
        if relpath in self.cache:
            return self.cache[relpath]
        p = self.repo / relpath
        if not p.is_file() or p.suffix != ".py":
            return None
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        try:
            tree = ast.parse(text, filename=relpath)
        except SyntaxError:
            return None

        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        funcs = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((node.lineno, getattr(node, "end_lineno", node.lineno), node.name, node))

        value_reads: dict[str, list[tuple[int, str]]] = {}
        assignments: list[dict[str, Any]] = []
        calls: list[dict[str, Any]] = []

        def dotted(n: ast.AST | None) -> str:
            if isinstance(n, ast.Name):
                return n.id
            if isinstance(n, ast.Attribute):
                left = dotted(n.value)
                return f"{left}.{n.attr}" if left else n.attr
            return ""

        def symbol_for(line: int) -> str:
            matches = [f for f in funcs if f[0] <= line <= f[1]]
            return min(matches, key=lambda x: x[1]-x[0])[2] if matches else "<module>"

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = dotted(node.func)
                if name:
                    calls.append({"line": node.lineno, "name": name, "symbol": symbol_for(node.lineno)})
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                lineno = node.lineno
                src = ast.get_source_segment(text, node) or ""
                assignments.append({"line": lineno, "symbol": symbol_for(lineno), "source": src[:1000]})

        result = {
            "text": text,
            "lines": lines,
            "tree": tree,
            "funcs": funcs,
            "calls": calls,
            "assignments": assignments,
        }
        self.cache[relpath] = result
        return result

    def context(self, relpath: str, line: int, radius: int = 5) -> list[str]:
        src = self.get(relpath)
        if not src:
            return []
        lines = src["lines"]
        lo = max(1, line-radius)
        hi = min(len(lines), line+radius)
        return [f"{i}: {lines[i-1]}" for i in range(lo, hi+1)]

    def symbol(self, relpath: str, line: int) -> str:
        src = self.get(relpath)
        if not src:
            return "<unknown>"
        matches = [f for f in src["funcs"] if f[0] <= line <= f[1]]
        return min(matches, key=lambda x: x[1]-x[0])[2] if matches else "<module>"

    def function_source(self, relpath: str, line: int) -> str:
        src = self.get(relpath)
        if not src:
            return ""
        matches = [f for f in src["funcs"] if f[0] <= line <= f[1]]
        if not matches:
            return "\n".join(src["lines"][max(0,line-4):line+4])
        start, end, _, _ = min(matches, key=lambda x: x[1]-x[0])
        return "\n".join(src["lines"][start-1:end])


def _term_from_evidence(evidence: str) -> str:
    m = re.search(r"term='([^']+)'", evidence or "")
    return m.group(1) if m else ""


def _contains_any(text: str, words: set[str]) -> list[str]:
    low = text.lower()
    return sorted(w for w in words if w in low)


def classify_one(index: SourceIndex, finding: dict[str, Any]) -> Classification:
    file = finding.get("file", "")
    line = int(finding.get("line") or 0)
    code = finding.get("code", "")
    term = _term_from_evidence(finding.get("evidence", ""))
    symbol = index.symbol(file, line) if line else finding.get("symbol", "<repository>")
    context = index.context(file, line, 7) if line else []
    func_source = index.function_source(file, line) if line else ""
    low = func_source.lower()

    # Repository-level structural finding: multiple potential authorities.
    if code == "D3-AUTH-102":
        return Classification(
            file=file, line=line, symbol=symbol, finding_code=code, term=term,
            classification="AUTHORITY_AMBIGUITY",
            confidence="HIGH",
            reason="Multiple planner/director implementations exist. Static presence alone is not a defect, but production reachability and write authority must be proven.",
            evidence=[finding.get("evidence", "")],
            action="TRACE_RUNTIME_REACHABILITY",
        )

    if code == "D3-STATE-401":
        return Classification(
            file=file, line=line, symbol=symbol, finding_code=code, term=term,
            classification="STATE_OWNERSHIP_REVIEW",
            confidence="HIGH",
            reason="Multiple Department 3 modules persist artifacts. Determine which are canonical, derived, historical, or legacy.",
            evidence=[finding.get("evidence", "")],
            action="MAP_WRITERS_AND_CONSUMERS",
        )

    decision_hits = _contains_any(low, DECISION_VERBS)
    exec_hits = _contains_any(low, EXECUTION_VERBS)
    creative_hits = _contains_any(low, CREATIVE_FIELDS)

    # Department 4 classification.
    if file in D4_FILES:
        vdc_reads = bool(re.search(r"\b(vdc|visual_direction|direction_contract|contract)\b", low))
        missing_value_fallback = bool(re.search(
            r"(?:\.get\([^)]*(?:layout|headline|cta|template|crop)[^)]*,\s*['\"]|"
            r"(?:layout|headline|cta|template|crop)\s*=\s*[^#\n]*(?:or\s+['\"]|if\s+not))",
            low,
            flags=re.I
        ))
        random_creative = bool(re.search(r"\brandom\.(choice|choices|randint|shuffle)\b", low))
        hardcoded_creative_choice = bool(re.search(
            r"(layout|template|headline|cta|crop)[^=\n]{0,30}=\s*['\"][A-Za-z0-9_\- ]+['\"]",
            low,
            flags=re.I,
        ))

        if random_creative:
            cls, conf, action = "UNAUTHORIZED_CREATIVE_AUTHORITY", "HIGH", "REPAIR"
            reason = "Department 4 contains random creative selection inside the affected function."
        elif missing_value_fallback and creative_hits:
            cls, conf, action = "POTENTIAL_FAIL_OPEN_DEFAULT", "HIGH", "INSPECT_AND_REPAIR_IF_PRODUCTION_REACHABLE"
            reason = "Department 4 appears to substitute creative values when expected creative input is absent."
        elif hardcoded_creative_choice and not vdc_reads:
            cls, conf, action = "POTENTIAL_CREATIVE_DECISION", "MEDIUM", "TRACE_CALLER_AND_INPUT_CONTRACT"
            reason = "Creative-looking value is assigned in Department 4 without an obvious VDC/contract read in the same function."
        elif vdc_reads and exec_hits:
            cls, conf, action = "LIKELY_DETERMINISTIC_EXECUTION", "MEDIUM", "VERIFY_WITH_TARGETED_TEST"
            reason = "Function references VDC/visual-direction data and mainly performs execution operations."
        else:
            cls, conf, action = "NEEDS_MANUAL_BEHAVIOR_TRACE", "LOW", "TRACE_CALLER_AND_TEST"
            reason = "Keyword hit alone is insufficient to determine whether this code chooses or merely executes creative direction."

        return Classification(
            file=file, line=line, symbol=symbol, finding_code=code, term=term,
            classification=cls, confidence=conf, reason=reason,
            evidence=context + [
                f"decision_verbs={decision_hits}",
                f"execution_verbs={exec_hits}",
                f"creative_fields={creative_hits}",
                f"vdc_read={vdc_reads}",
            ],
            action=action,
        )

    # Legacy/default findings in Department 3.
    if code == "D3-LEGACY-301":
        canonical = file in CANONICAL_D3_FILES
        if canonical:
            cls = "CANONICAL_D3_REVIEW"
            conf = "MEDIUM"
            reason = "Default/fallback terminology occurs inside canonical Department 3 code; behavior must fail closed for missing authoritative evidence and critical creative inputs."
            action = "VERIFY_FAIL_CLOSED"
        elif file in LEGACY_AUTHORITY_CANDIDATES:
            cls = "LEGACY_AUTHORITY_CANDIDATE"
            conf = "HIGH"
            reason = "File is one of the older planner/intelligence/agent authority candidates. Production reachability must be proven or explicitly quarantined."
            action = "TRACE_RUNTIME_REACHABILITY"
        else:
            cls = "NON_AUTHORITY_DEFAULT_REVIEW"
            conf = "LOW"
            reason = "Default/legacy token may be schema/storage compatibility rather than creative authority."
            action = "VERIFY_CONSUMER_BEHAVIOR"

        return Classification(
            file=file, line=line, symbol=symbol, finding_code=code, term=term,
            classification=cls, confidence=conf, reason=reason,
            evidence=context,
            action=action,
        )

    return Classification(
        file=file, line=line, symbol=symbol, finding_code=code, term=term,
        classification="UNCLASSIFIED",
        confidence="LOW",
        reason="No conservative automatic behavioral rule applies.",
        evidence=context,
        action="MANUAL_REVIEW",
    )


def discover_import_reachability(repo: Path, audit: dict[str, Any]) -> dict[str, Any]:
    graph = audit.get("import_graph", {})
    starts = [
        "app.py",
        "src/execution/stages.py",
        "src/hardening/pipeline.py",
        "run_department4_certification.py",
    ]

    def reachable(start: str) -> set[str]:
        seen = set()
        stack = [start]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(graph.get(n, []))
        return seen

    reach = {s: sorted(reachable(s)) for s in starts if s in graph or (repo / s).exists()}
    legacy = sorted(LEGACY_AUTHORITY_CANDIDATES)
    canonical = sorted(CANONICAL_D3_FILES)
    return {
        "entrypoint_reachability": reach,
        "legacy_candidates": {
            f: [s for s, nodes in reach.items() if f in nodes] for f in legacy
        },
        "canonical_authority": {
            f: [s for s, nodes in reach.items() if f in nodes] for f in canonical
        },
    }


def run_pytest(repo: Path) -> dict[str, Any]:
    targets = [
        "tests/test_visual_art_director.py",
        "tests/test_vdc_branded_qa.py",
        "tests/test_department4_production_contract.py",
        "tests/test_brand_composer.py",
        "tests/test_image_processing_planner.py",
        "tests/test_image_prompt_generator.py",
        "tests/test_instagram_story_support.py",
    ]
    existing = [t for t in targets if (repo / t).is_file()]
    if not existing:
        return {"ran": False, "reason": "No targeted test files found."}
    cmd = [sys.executable, "-m", "pytest", "-q", *existing]
    proc = subprocess.run(cmd, cwd=repo, text=True, capture_output=True)
    return {
        "ran": True,
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-20000:],
        "stderr": proc.stderr[-8000:],
    }


def summarize(classifications: list[Classification]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in classifications:
        out[c.classification] = out.get(c.classification, 0) + 1
    return dict(sorted(out.items(), key=lambda x: (-x[1], x[0])))


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Department 3 — Phase 2 Behavioral Classification",
        "",
        "This phase performs classification only. It does not modify production source.",
        "",
        "## Classification Summary",
    ]
    for k, v in report["summary"]["classifications"].items():
        lines.append(f"- **{k}**: {v}")
    lines += [
        "",
        "## Runtime/Import Reachability",
    ]
    for f, starts in report["reachability"]["legacy_candidates"].items():
        lines.append(f"- `{f}`: " + (", ".join(starts) if starts else "not statically reachable from audited entrypoints"))
    lines += ["", "## Findings"]
    for i, c in enumerate(report["classifications"], 1):
        lines += [
            f"### {i}. {c['classification']} — {c['file']}:{c['line']}",
            f"- Original code: `{c['finding_code']}`",
            f"- Symbol: `{c['symbol']}`",
            f"- Confidence: **{c['confidence']}**",
            f"- Reason: {c['reason']}",
            f"- Required action: **{c['action']}**",
        ]
        if c["evidence"]:
            lines.append("- Evidence:")
            for ev in c["evidence"][:12]:
                lines.append(f"  - `{str(ev).replace('`','')}`")
        lines.append("")
    lines += [
        "## Targeted Existing Tests",
        f"- Ran: `{report['targeted_tests'].get('ran')}`",
        f"- Return code: `{report['targeted_tests'].get('returncode')}`",
        "",
        "```text",
        report["targeted_tests"].get("stdout", "")[-8000:],
        "```",
        "",
        "## Modification Decision",
        "Do not modify production code until every HIGH-confidence authority ambiguity or fail-open/default classification is traced to its production caller and input contract.",
    ]
    return "\n".join(lines) + "\n"


def run(repo: Path, audit_path: Path, output_dir: Path, run_tests: bool = True) -> dict[str, Any]:
    repo = repo.resolve()
    audit_path = audit_path.resolve()
    output_dir = output_dir.resolve()

    if not (repo / "app.py").is_file():
        raise SystemExit("Run from the instagram-agent repository root.")
    if not audit_path.is_file():
        raise SystemExit(f"Missing Phase 1 audit JSON: {audit_path}")

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    index = SourceIndex(repo)
    classifications = [classify_one(index, f) for f in audit.get("findings", [])]
    reachability = discover_import_reachability(repo, audit)
    tests = run_pytest(repo) if run_tests else {"ran": False, "reason": "disabled"}

    report = {
        "schema_version": "department3.phase2.behavioral_classification.v1",
        "repository": str(repo),
        "phase1_audit": str(audit_path),
        "summary": {
            "input_findings": len(audit.get("findings", [])),
            "classifications": summarize(classifications),
            "targeted_tests_pass": tests.get("returncode") == 0 if tests.get("ran") else None,
        },
        "reachability": reachability,
        "classifications": [asdict(c) for c in classifications],
        "targeted_tests": tests,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    j = output_dir / "department3-phase2-behavioral-classification.json"
    m = output_dir / "department3-phase2-behavioral-classification.md"
    j.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    m.write_text(markdown(report), encoding="utf-8")

    print("Department 3 Phase 2 behavioral classification completed")
    print(f"- Input findings: {report['summary']['input_findings']}")
    for k, v in report["summary"]["classifications"].items():
        print(f"- {k}: {v}")
    if tests.get("ran"):
        print(f"- Targeted tests return code: {tests['returncode']}")
    print(f"- JSON: {j}")
    print(f"- Markdown: {m}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--audit",
        default="output/audits/department3/department3-phase1-authority-audit.json",
    )
    parser.add_argument(
        "--output",
        default="output/audits/department3",
    )
    parser.add_argument("--no-tests", action="store_true")
    args = parser.parse_args()
    run(Path(args.repo), Path(args.audit), Path(args.output), run_tests=not args.no_tests)


if __name__ == "__main__":
    main()
