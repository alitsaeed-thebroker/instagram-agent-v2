"""Run the separate library QA gate for validated candidates in one batch."""
import argparse,json
from pathlib import Path
from src.creative_library import CreativeIntelligenceLibrary
from src.utils.config import PROJECT_ROOT
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("batch",type=Path);args=parser.parse_args();payload=json.loads(args.batch.read_text(encoding="utf-8"))
    library=CreativeIntelligenceLibrary.default(PROJECT_ROOT);admitted=[];observations={x["observation_id"]:x for x in payload["observations"]}
    for candidate in payload["pattern_candidates"]:
        if candidate["status"] not in {"VALIDATED","MERGED"} or candidate["cross_source_count"]<3 or candidate["source_diversity"]<2:continue
        support=[observations[x] for x in candidate["supporting_observation_ids"]]
        library.admit_research_candidate(candidate,support,approved_by="phase_3_controlled_library_qa");admitted.append(candidate["candidate_id"])
    print(json.dumps({"admitted":admitted,"library_version":library.load()["library_version"]},indent=2))
