from pathlib import Path
from tools.department3_phase2_behavioral_classification import run

if __name__ == "__main__":
    run(
        Path("."),
        Path("output/audits/department3/department3-phase1-authority-audit.json"),
        Path("output/audits/department3"),
        run_tests=True,
    )
