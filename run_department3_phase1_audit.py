from pathlib import Path
from tools.department3_phase1_audit import run

if __name__ == "__main__":
    run(Path("."), Path("output/audits/department3"))
