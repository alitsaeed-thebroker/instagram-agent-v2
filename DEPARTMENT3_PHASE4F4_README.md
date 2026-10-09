# Department 3 Phase 4F.4 — Backward-Compatibility Repair

Phase 4F.3 hardened real-project source discovery correctly, but it removed helper functions
that earlier Phase 4F regression tests imported directly.

That caused pytest collection errors even though Department 3 production logic remained healthy.

Phase 4F.4 restores these helper names as wrappers around the hardened Phase 4F.3 logic:

- `_artifact_matches_project`
- `_text_mentions_project`
- `_is_forbidden_source`
- `_walk_json_files`
- `_opportunities_from_inventory`
- `_score_check`

The stricter source rules remain unchanged:

- audit files are excluded
- release/provenance files are excluded
- backups/archives are excluded
- only semantically valid visual opportunity/inventory sources may certify Phase 4F

## Apply

Extract directly into the repository root, then run:

```powershell
python install_phase4f4.py
python -m pytest -q tests/test_department3_phase4f4_compatibility.py
python -m pytest -q
```

After the full suite is green again, do **not** rerun certification yet unless a valid Beverly Hills
visual-opportunity/inventory artifact exists. The Phase 4F.3 result already proved that none is
currently available in the accepted source families.
