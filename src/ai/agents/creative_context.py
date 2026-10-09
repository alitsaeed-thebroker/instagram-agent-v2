"""Compact advisory input; full evidence remains in Department 2 artifacts."""
from copy import deepcopy
import hashlib
import json

def creative_knowledge_context(knowledge):
    graph=knowledge.get("canonical_intelligence") or {}
    if not graph:
        return deepcopy(knowledge)
    graph=deepcopy(graph)
    evidence={}
    for fact in graph.get("facts", []):
        fact["has_conflicts"]=bool(fact.pop("conflicts", []))
        fact["provenance"]=[{key:value for key,value in record.items() if key in {
            "evidence_id", "source_project", "source_file", "source_id", "source_sha256",
            "page", "source_page", "line_range", "paragraph", "table_index", "row_index",
            "extraction_method", "support_status", "structure_status"}}
            for record in fact.get("provenance", [])]
        refs=[]
        for record in fact["provenance"]:
            key=hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()[:20]
            evidence[key]=record;refs.append(key)
        fact["provenance_refs"]=refs
        fact.pop("provenance")
    graph["evidence_catalog"]=evidence
    graph["conflict_count"]=len(graph.pop("conflicts", []))
    result={"project_identity":deepcopy(knowledge.get("project_identity", {})),
        "canonical_intelligence":graph,
        "full_knowledge_sha256":hashlib.sha256(json.dumps(knowledge,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "source_truth_policy":"Only VERIFIED marketing_eligible facts authorize public claims. Conflicts and missing facts remain unavailable. Full source text remains upstream, addressed by evidence IDs and exact locators. Unit dimensions and geometry must never be inferred."}
    if len(json.dumps(result,ensure_ascii=False))>180000:
        raise ValueError("Creative evidence context exceeds safe input budget; select a narrower authoritative content batch")
    return result
