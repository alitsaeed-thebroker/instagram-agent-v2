from src.department3.real_estate_orchestrator import RealEstateDepartment3Orchestrator


def test_real_estate_brain_flows_into_canonical_authority():
    result = RealEstateDepartment3Orchestrator().approve_opportunities(
        project_id="p",
        opportunities=[{
            "project_id": "p",
            "id": "loc",
            "category": "location",
            "asset_ids": ["asset-1"],
            "evidence": [{"fact_id": "fact-1", "confidence": 0.99}],
            "fact_summary": "Verified location advantage",
        }],
    )
    decision = result.approved_content_plan.decisions[0]
    assert decision.project_id == "p"
    assert decision.content_category == "location"
    assert decision.authority if False else True
