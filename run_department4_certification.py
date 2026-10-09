"""Run the isolated Phase 6 Department 4 production certification."""
from pathlib import Path
from src.simulation.production_certification import run_department4_production_certification

if __name__ == "__main__":
    print(run_department4_production_certification(Path(__file__).resolve().parent))
