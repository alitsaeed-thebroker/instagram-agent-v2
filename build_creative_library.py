"""Initialize, validate, or deliberately rebuild the offline seed library."""
import argparse
from src.creative_library import CreativeIntelligenceLibrary
from src.creative_library.seeds import anti_patterns,seed_patterns
from src.utils.config import PROJECT_ROOT
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--rebuild-seed",action="store_true");args=parser.parse_args()
    library=CreativeIntelligenceLibrary.default(PROJECT_ROOT)
    if args.rebuild_seed:
        payload=library._payload(seed_patterns(),anti_patterns(),"1.0.0");library._write(payload)
    else:payload=library.initialize()
    print(f"{library.path}: {payload['metrics']}")
