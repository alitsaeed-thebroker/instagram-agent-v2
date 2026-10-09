# Department 3 Phase 4F.1 — Real Artifact Discovery Fix

Phase 4F failed before certification because the runner required the project name to appear
in an artifact's filesystem path.

The live repository can store canonical project artifacts under generic filenames and
directories, while the JSON itself contains `project_id`, `project_name`, `source_project`,
or equivalent project identity.

This patch changes discovery so a file can match the project by:

1. filesystem path, or
2. JSON content identity.

It also searches generic JSON files under `output/`, `input/`, and `data/` when necessary.

No Department 3 authority behavior is modified.

## Apply

Replace:

`src/department3/phase4f_certification.py`

with the version in this ZIP.

## Run

```powershell
python -m pytest -q tests/test_department3_phase4f1_discovery.py
python run_department3_phase4f_certification.py --project "Beverly Hills"
python -m pytest -q
```

If certification still cannot find the real artifact, the new error includes the directories
that were searched, which makes the next mapping correction precise.
