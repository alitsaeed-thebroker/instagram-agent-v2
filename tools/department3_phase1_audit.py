from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

DEPARTMENT3_HINTS = {
    "src/content",
    "src/planning",
    "src/creative",
    "src/creative_intelligence",
    "src/campaign_intelligence",
    "src/ai/agents/content_planner.py",
    "src/ai/agents/campaign_planner.py",
    "src/ai/agents/marketing_strategy_agent.py",
    "src/ai/agents/creative_director_agent.py",
    "src/ai/agents/visual_art_director_agent.py",
    "src/creative/visual_art_director.py",
    "src/creative/visual_direction.py",
    "src/creative/production_contract.py",
}

CREATIVE_AUTHORITY_TERMS = {
    "creative", "direction", "visual_direction", "visual art director",
    "visual_art_director", "layout", "composition", "headline", "cta",
    "crop", "hierarchy", "template", "preset", "fallback", "brand_composer",
    "composer", "marketing objective", "marketing_objective",
}

BYPASS_TERMS = {
    "fallback", "default", "legacy", "preset", "template", "override",
    "random", "compatibility", "deprecated", "placeholder", "mock",
    "synthetic", "auto_layout", "auto layout", "just make",
}

VDC_TERMS = {
    "vdc", "visual_direction", "visual direction", "contract_id",
    "production_item_id", "signed", "signature", "hash",
}

DEPT4_HINTS = {
    "src/branding/composer.py",
    "src/image_processing",
    "src/image_prompts",
    "src/production",
    "src/render",
    "src/creative/production_contract.py",
}

ENTRYPOINT_HINTS = {
    "app.py",
    "src/execution/stages.py",
    "src/hardening/pipeline.py",
    "run_campaign_intelligence.py",
    "run_creative_research.py",
    "run_department4_certification.py",
}


@dataclass
class Finding:
    severity: str
    code: str
    file: str
    line: int
    symbol: str
    message: str
    evidence: str


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path: Path, repo: Path) -> str:
    try:
        return path.relative_to(repo).as_posix()
    except ValueError:
        return path.as_posix()


def py_files(repo: Path) -> list[Path]:
    ignored = {".git", ".venv", "venv", "__pycache__", "output", "archive", "data"}
    files = []
    for p in repo.rglob("*.py"):
        if any(part in ignored for part in p.parts):
            continue
        files.append(p)
    return sorted(files)


def is_department3_path(rp: str) -> bool:
    if rp.startswith(("src/content/", "src/planning/", "src/creative/", "src/creative_intelligence/", "src/campaign_intelligence/")):
        return True
    return rp in DEPARTMENT3_HINTS


def is_dept4_path(rp: str) -> bool:
    return (
        rp == "src/branding/composer.py"
        or rp.startswith(("src/image_processing/", "src/image_prompts/", "src/production/", "src/render/"))
    )


def dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def safe_source(lines: list[str], lineno: int, end_lineno: int | None = None) -> str:
    if lineno <= 0 or lineno > len(lines):
        return ""
    end = end_lineno or lineno
    end = max(lineno, min(end, lineno + 4, len(lines)))
    return "\n".join(lines[lineno - 1:end]).strip()[:700]


def scan_python_file(path: Path, repo: Path) -> dict[str, Any]:
    rp = rel(path, repo)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    record: dict[str, Any] = {
        "path": rp,
        "sha256": sha256_file(path),
        "department3": is_department3_path(rp),
        "department4": is_dept4_path(rp),
        "imports": [],
        "functions": [],
        "classes": [],
        "calls": [],
        "writes": [],
        "term_hits": defaultdict(list),
        "parse_error": None,
    }

    lower = text.lower()
    for term in sorted(CREATIVE_AUTHORITY_TERMS | BYPASS_TERMS | VDC_TERMS):
        start = 0
        term_l = term.lower()
        while True:
            idx = lower.find(term_l, start)
            if idx < 0:
                break
            line_no = lower.count("\n", 0, idx) + 1
            record["term_hits"][term].append(line_no)
            start = idx + max(1, len(term_l))

    try:
        tree = ast.parse(text, filename=rp)
    except SyntaxError as exc:
        record["parse_error"] = f"{exc.__class__.__name__}: {exc}"
        record["term_hits"] = dict(record["term_hits"])
        return record

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    def enclosing_symbol(node: ast.AST) -> str:
        cur = node
        while cur in parents:
            cur = parents[cur]
            if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return cur.name
            if isinstance(cur, ast.ClassDef):
                return cur.name
        return "<module>"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                record["imports"].append(n.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            record["imports"].append(module)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            record["functions"].append({
                "name": node.name,
                "line": node.lineno,
                "args": [a.arg for a in node.args.args],
                "decorators": [dotted_name(d) for d in node.decorator_list],
            })
        elif isinstance(node, ast.ClassDef):
            record["classes"].append({
                "name": node.name,
                "line": node.lineno,
                "bases": [dotted_name(b) for b in node.bases],
            })
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name:
                record["calls"].append({
                    "name": name,
                    "line": getattr(node, "lineno", 0),
                    "symbol": enclosing_symbol(node),
                })

            # Generic JSON/text writes, useful for contract/history authority mapping.
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"write_text", "write_bytes", "dump", "dumps"}:
                record["writes"].append({
                    "call": name,
                    "line": getattr(node, "lineno", 0),
                    "symbol": enclosing_symbol(node),
                    "source": safe_source(lines, getattr(node, "lineno", 0)),
                })

    record["imports"] = sorted(set(record["imports"]))
    record["term_hits"] = dict(record["term_hits"])
    return record


def module_for_path(rp: str) -> str:
    if not rp.endswith(".py"):
        return ""
    p = rp[:-3]
    if p.endswith("/__init__"):
        p = p[:-9]
    return p.replace("/", ".")


def build_import_graph(records: list[dict[str, Any]]) -> dict[str, list[str]]:
    known = {module_for_path(r["path"]): r["path"] for r in records}
    graph: dict[str, list[str]] = defaultdict(list)
    for r in records:
        src = r["path"]
        for imp in r["imports"]:
            candidates = [m for m in known if imp == m or imp.startswith(m + ".") or m.startswith(imp + ".")]
            if candidates:
                best = max(candidates, key=len)
                graph[src].append(known[best])
    return {k: sorted(set(v)) for k, v in sorted(graph.items())}


def paths_reachable(graph: dict[str, list[str]], starts: Iterable[str], max_depth: int = 20) -> set[str]:
    visited: set[str] = set()
    q = deque((s, 0) for s in starts)
    while q:
        node, depth = q.popleft()
        if node in visited or depth > max_depth:
            continue
        visited.add(node)
        for nxt in graph.get(node, []):
            q.append((nxt, depth + 1))
    return visited


def make_findings(repo: Path, records: list[dict[str, Any]], graph: dict[str, list[str]]) -> list[Finding]:
    findings: list[Finding] = []
    by_path = {r["path"]: r for r in records}

    # 1) Parse errors in relevant files.
    for r in records:
        if r["parse_error"] and (r["department3"] or r["department4"]):
            findings.append(Finding(
                "CRITICAL", "D3-PARSE-001", r["path"], 0, "<module>",
                "Relevant Department 3/4 Python file cannot be parsed.",
                r["parse_error"],
            ))

    # 2) Brand Composer / deterministic Dept 4 creative-authority terms.
    for r in records:
        if not r["department4"]:
            continue
        suspicious_terms = {"headline", "cta", "marketing_objective", "marketing objective", "template", "preset", "fallback", "layout"}
        for term in suspicious_terms:
            for line in r["term_hits"].get(term, [])[:8]:
                findings.append(Finding(
                    "HIGH", "D3-AUTH-201", r["path"], line, "<unknown>",
                    "Department 4 contains a creative-authority indicator that must be classified as deterministic implementation or unauthorized creative decision.",
                    f"term={term!r}",
                ))

    # 3) VDC/contract implementation existence.
    vdc_paths = [
        r["path"] for r in records
        if any(r["term_hits"].get(t) for t in ("vdc", "visual_direction", "contract_id"))
        and (r["department3"] or r["department4"])
    ]
    if not vdc_paths:
        findings.append(Finding(
            "CRITICAL", "D3-VDC-001", "<repository>", 0, "<repository>",
            "No Visual Direction Contract implementation was detected in current production source.",
            "Search terms: vdc, visual_direction, contract_id",
        ))

    # 4) Production-item identity binding signal.
    contract_candidates = [r for r in records if "contract" in r["path"] or "visual_direction" in r["path"]]
    if contract_candidates and not any(r["term_hits"].get("production_item_id") for r in contract_candidates):
        findings.append(Finding(
            "CRITICAL", "D3-VDC-002", "<repository>", 0, "<repository>",
            "Contract/VDC code exists but production_item_id binding was not detected.",
            ", ".join(r["path"] for r in contract_candidates),
        ))

    # 5) Entrypoints bypassing Department 3 into Department 4.
    dept3_paths = {r["path"] for r in records if r["department3"]}
    dept4_paths = {r["path"] for r in records if r["department4"]}
    entrypoints = [p for p in ENTRYPOINT_HINTS if p in by_path]
    for ep in entrypoints:
        reachable = paths_reachable(graph, [ep])
        if reachable & dept4_paths and not reachable & dept3_paths:
            findings.append(Finding(
                "CRITICAL", "D3-BYPASS-101", ep, 0, "<module>",
                "Entrypoint can reach Department 4 code without any detected Department 3 module in the static import path.",
                f"dept4={sorted(reachable & dept4_paths)}",
            ))

    # 6) Legacy/default/fallback creative behavior in D3.
    for r in records:
        if not r["department3"]:
            continue
        for term in ("legacy", "fallback", "default", "template", "preset", "override", "random"):
            hits = r["term_hits"].get(term, [])
            for line in hits[:10]:
                findings.append(Finding(
                    "MEDIUM", "D3-LEGACY-301", r["path"], line, "<unknown>",
                    "Department 3 contains legacy/default/fallback/template logic requiring authority review.",
                    f"term={term!r}",
                ))

    # 7) Multiple obvious planner/creative director implementations.
    authority_files = []
    authority_name_pattern = re.compile(r"(content_planner|campaign_planner|creative_director|visual_art_director|visual_direction)", re.I)
    for r in records:
        if authority_name_pattern.search(r["path"]):
            authority_files.append(r["path"])
    if len(authority_files) >= 5:
        findings.append(Finding(
            "HIGH", "D3-AUTH-102", "<repository>", 0, "<repository>",
            "Multiple creative/planning authority implementations exist; canonical ownership must be explicitly proven.",
            ", ".join(sorted(authority_files)),
        ))

    # 8) Direct writes by multiple D3 modules are important for stale/multiple-authority review.
    writer_files = [r["path"] for r in records if r["department3"] and r["writes"]]
    if len(writer_files) >= 3:
        findings.append(Finding(
            "MEDIUM", "D3-STATE-401", "<repository>", 0, "<repository>",
            "Multiple Department 3 modules persist state/artifacts directly; cache/history authority needs explicit ownership.",
            ", ".join(sorted(writer_files)),
        ))

    return findings


def authority_inventory(records: list[dict[str, Any]]) -> dict[str, Any]:
    result = {
        "department3_files": [],
        "department4_files": [],
        "visual_art_director_files": [],
        "visual_direction_contract_files": [],
        "brand_composer_files": [],
        "planner_files": [],
        "entrypoint_files": [],
    }
    for r in records:
        p = r["path"]
        if r["department3"]:
            result["department3_files"].append(p)
        if r["department4"]:
            result["department4_files"].append(p)
        if "visual_art_director" in p:
            result["visual_art_director_files"].append(p)
        if "visual_direction" in p or "production_contract" in p:
            result["visual_direction_contract_files"].append(p)
        if "composer" in p:
            result["brand_composer_files"].append(p)
        if "planner" in p or "campaign_intelligence" in p:
            result["planner_files"].append(p)
        if p in ENTRYPOINT_HINTS:
            result["entrypoint_files"].append(p)
    return {k: sorted(v) for k, v in result.items()}


def report_markdown(report: dict[str, Any]) -> str:
    lines = []
    lines.append("# Department 3 — Phase 1 Authority & Boundary Audit")
    lines.append("")
    lines.append(f"- Repository: `{report['repository']}`")
    lines.append(f"- Python files scanned: **{report['summary']['python_files_scanned']}**")
    lines.append(f"- Department 3 candidates: **{report['summary']['department3_files']}**")
    lines.append(f"- Department 4 candidates: **{report['summary']['department4_files']}**")
    lines.append(f"- Findings: **{report['summary']['findings']}**")
    lines.append("")

    lines.append("## Authority Inventory")
    for key, values in report["authority_inventory"].items():
        lines.append(f"### {key}")
        if values:
            for v in values:
                lines.append(f"- `{v}`")
        else:
            lines.append("- None detected")
        lines.append("")

    lines.append("## Findings")
    if not report["findings"]:
        lines.append("No static findings were emitted. This is not a production certification; dynamic tests are still required.")
    else:
        for i, f in enumerate(report["findings"], 1):
            lines.append(f"### {i}. {f['severity']} — {f['code']}")
            lines.append(f"- File: `{f['file']}`")
            lines.append(f"- Line: `{f['line']}`")
            lines.append(f"- Message: {f['message']}")
            lines.append(f"- Evidence: `{f['evidence']}`")
            lines.append("")

    lines.append("## Static Import Graph — Relevant Edges")
    relevant = set(report["authority_inventory"]["department3_files"]) | set(report["authority_inventory"]["department4_files"]) | set(report["authority_inventory"]["entrypoint_files"])
    for src, dsts in report["import_graph"].items():
        filtered = [d for d in dsts if src in relevant or d in relevant]
        if filtered:
            lines.append(f"- `{src}`")
            for d in filtered:
                lines.append(f"  - → `{d}`")

    lines.append("")
    lines.append("## Next Step")
    lines.append("Use the JSON report as the source of truth for Phase 2 code changes. Do not freeze Department 3 from this static audit alone.")
    return "\n".join(lines) + "\n"


def run(repo: Path, output_dir: Path) -> dict[str, Any]:
    repo = repo.resolve()
    output_dir = output_dir.resolve()
    if not (repo / "app.py").is_file():
        raise SystemExit(f"Not an instagram-agent repository root: missing {repo / 'app.py'}")
    if not (repo / "src").is_dir():
        raise SystemExit(f"Not an instagram-agent repository root: missing {repo / 'src'}")

    files = py_files(repo)
    records = [scan_python_file(p, repo) for p in files]
    graph = build_import_graph(records)
    findings = make_findings(repo, records, graph)
    inv = authority_inventory(records)

    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    findings = sorted(findings, key=lambda f: (sev_order.get(f.severity, 9), f.file, f.line, f.code))

    report = {
        "schema_version": "department3.phase1.audit.v1",
        "repository": str(repo),
        "summary": {
            "python_files_scanned": len(records),
            "department3_files": len(inv["department3_files"]),
            "department4_files": len(inv["department4_files"]),
            "findings": len(findings),
            "critical": sum(1 for f in findings if f.severity == "CRITICAL"),
            "high": sum(1 for f in findings if f.severity == "HIGH"),
            "medium": sum(1 for f in findings if f.severity == "MEDIUM"),
            "low": sum(1 for f in findings if f.severity == "LOW"),
        },
        "authority_inventory": inv,
        "findings": [asdict(f) for f in findings],
        "import_graph": graph,
        "files": records,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "department3-phase1-authority-audit.json"
    md_path = output_dir / "department3-phase1-authority-audit.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(report_markdown(report), encoding="utf-8")

    print("Department 3 Phase 1 audit completed")
    print(f"- Python files scanned: {report['summary']['python_files_scanned']}")
    print(f"- Department 3 candidates: {report['summary']['department3_files']}")
    print(f"- Department 4 candidates: {report['summary']['department4_files']}")
    print(f"- Findings: {report['summary']['findings']}")
    print(f"  - CRITICAL: {report['summary']['critical']}")
    print(f"  - HIGH: {report['summary']['high']}")
    print(f"  - MEDIUM: {report['summary']['medium']}")
    print(f"  - LOW: {report['summary']['low']}")
    print(f"- JSON: {json_path}")
    print(f"- Markdown: {md_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Department 3 Phase 1 authority/boundary audit")
    parser.add_argument("--repo", default=".", help="instagram-agent repository root")
    parser.add_argument("--output", default="output/audits/department3", help="audit output directory")
    args = parser.parse_args()
    run(Path(args.repo), Path(args.output))


if __name__ == "__main__":
    main()
