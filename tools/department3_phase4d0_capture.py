from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

LEGACY_SYMBOLS = {
    "ContentPlanner": "src.ai.agents.content_planner",
    "CreativeDirectorAgent": "src.ai.agents.creative_director_agent",
    "MarketingStrategyAgent": "src.ai.agents.marketing_strategy_agent",
    "CampaignPlanner": "src.ai.agents.campaign_planner",
    "VisualArtDirectorAgent": "src.ai.agents.visual_art_director_agent",
    "PlanningEngine": "src.planning.engine",
    "VisualOpportunityEngine": "src.planning.engine",
}

TARGETS = ("app.py", "src/execution/stages.py")


def dotted(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def enclosing_symbol(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    cur = node
    while cur in parents:
        cur = parents[cur]
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return cur.name
        if isinstance(cur, ast.ClassDef):
            return cur.name
    return "<module>"


def source_window(lines: list[str], start: int, end: int, radius: int = 5) -> list[str]:
    lo = max(1, start - radius)
    hi = min(len(lines), end + radius)
    return [f"{i}: {lines[i-1]}" for i in range(lo, hi + 1)]


def analyze(path: Path, repo: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines()

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    imports: dict[str, str] = {}
    legacy_imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = f"{module}.{alias.name}" if module else alias.name
                if alias.name in LEGACY_SYMBOLS or module in set(LEGACY_SYMBOLS.values()):
                    legacy_imports.append({
                        "line": node.lineno,
                        "module": module,
                        "name": alias.name,
                        "local_name": local,
                        "source": ast.get_source_segment(text, node) or "",
                    })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name] = alias.name

    calls = []
    assignments = []
    attribute_calls = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            leaf = name.split(".")[-1] if name else ""
            resolved = imports.get(name, imports.get(leaf, ""))

            legacy_module = None
            legacy_symbol = None
            if leaf in LEGACY_SYMBOLS:
                legacy_symbol = leaf
                legacy_module = LEGACY_SYMBOLS[leaf]
            elif resolved:
                for symbol, module in LEGACY_SYMBOLS.items():
                    if resolved == f"{module}.{symbol}" or resolved.startswith(module + "."):
                        legacy_symbol = symbol
                        legacy_module = module
                        break

            # Calls on likely legacy instances such as planner.run()
            if leaf in {"run", "build", "plan", "generate"} and isinstance(node.func, ast.Attribute):
                base = dotted(node.func.value)
                attribute_calls.append({
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "call": name,
                    "base": base,
                    "enclosing_symbol": enclosing_symbol(node, parents),
                    "source": ast.get_source_segment(text, node) or "",
                    "context": source_window(
                        lines,
                        node.lineno,
                        getattr(node, "end_lineno", node.lineno),
                    ),
                })

            if legacy_module:
                calls.append({
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "legacy_symbol": legacy_symbol,
                    "legacy_module": legacy_module,
                    "call": name,
                    "enclosing_symbol": enclosing_symbol(node, parents),
                    "source": ast.get_source_segment(text, node) or "",
                    "context": source_window(
                        lines,
                        node.lineno,
                        getattr(node, "end_lineno", node.lineno),
                    ),
                })

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            src = ast.get_source_segment(text, node) or ""
            if any(symbol in src for symbol in LEGACY_SYMBOLS):
                assignments.append({
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "enclosing_symbol": enclosing_symbol(node, parents),
                    "source": src,
                    "context": source_window(
                        lines,
                        node.lineno,
                        getattr(node, "end_lineno", node.lineno),
                    ),
                })

    return {
        "path": path.relative_to(repo).as_posix(),
        "legacy_imports": legacy_imports,
        "legacy_constructor_calls": calls,
        "legacy_related_assignments": assignments,
        "candidate_instance_method_calls": attribute_calls,
    }


def main() -> None:
    repo = Path.cwd().resolve()
    if not (repo / "app.py").is_file():
        raise SystemExit("Run from the instagram-agent repository root.")

    results = []
    for rel in TARGETS:
        p = repo / rel
        if not p.is_file():
            raise SystemExit(f"Missing required live target: {rel}")
        results.append(analyze(p, repo))

    report = {
        "schema_version": "department3.phase4d0.exact_legacy_callsite_capture.v1",
        "repository": str(repo),
        "targets": results,
        "summary": {
            "legacy_imports": sum(len(x["legacy_imports"]) for x in results),
            "legacy_constructor_calls": sum(len(x["legacy_constructor_calls"]) for x in results),
            "legacy_related_assignments": sum(len(x["legacy_related_assignments"]) for x in results),
            "candidate_instance_method_calls": sum(len(x["candidate_instance_method_calls"]) for x in results),
        },
    }

    out = repo / "output" / "audits" / "department3"
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "department3-phase4d0-exact-legacy-callsites.json"
    md_path = out / "department3-phase4d0-exact-legacy-callsites.md"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Department 3 Phase 4D.0 — Exact Legacy Live Call Sites",
        "",
        f"- Legacy imports: **{report['summary']['legacy_imports']}**",
        f"- Legacy constructor calls: **{report['summary']['legacy_constructor_calls']}**",
        f"- Legacy-related assignments: **{report['summary']['legacy_related_assignments']}**",
        f"- Candidate instance method calls: **{report['summary']['candidate_instance_method_calls']}**",
        "",
    ]
    for target in results:
        lines += [f"## {target['path']}", ""]
        for key in (
            "legacy_imports",
            "legacy_constructor_calls",
            "legacy_related_assignments",
            "candidate_instance_method_calls",
        ):
            lines.append(f"### {key}")
            items = target[key]
            if not items:
                lines.append("- None")
            else:
                for item in items:
                    lines.append(f"- line {item.get('line')}: `{item.get('source','')}`")
                    if item.get("enclosing_symbol"):
                        lines.append(f"  - enclosing: `{item['enclosing_symbol']}`")
                    if item.get("legacy_module"):
                        lines.append(f"  - module: `{item['legacy_module']}`")
                    if item.get("context"):
                        lines.append("  - context:")
                        for row in item["context"]:
                            lines.append(f"    - `{row.replace('`','')}`")
            lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print("Department 3 Phase 4D.0 exact legacy call-site capture completed")
    for k, v in report["summary"].items():
        print(f"- {k}: {v}")
    print(f"- JSON: {json_path}")
    print(f"- Markdown: {md_path}")
    print("- Production files modified: 0")


if __name__ == "__main__":
    main()
