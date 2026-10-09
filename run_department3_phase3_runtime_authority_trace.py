from pathlib import Path
from tools.department3_phase3_runtime_authority_trace import run

if __name__ == "__main__":
    run(Path("."), Path("output/audits/department3"))
