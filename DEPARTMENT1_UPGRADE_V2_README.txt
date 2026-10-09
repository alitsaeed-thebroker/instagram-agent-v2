Instagram Agent — Department 1 Upgrade v2

PURPOSE
-------
This is the superseding Department 1 package. Use this instead of both earlier ZIPs.

It combines:

A) Canonical Department 1 cognition:
   INPUT -> READ -> UNDERSTAND -> ANALYZE -> CLASSIFY -> EXTRACT -> DEPARTMENT 2

B) The four correctness fixes from the Department 1 audit:
   1. Correct source-utilization math
   2. Read-only evaluator
   3. Candidate-only recovery (no regex match becomes VERIFIED/recovered)
   4. Canonical-coverage-based completeness

C) Corpus-boundary protection:
   Recovery/evaluation may only inspect original sources explicitly authorized
   by output/manifests/<project>-run-manifest.json -> source_file_hashes.

FILES INCLUDED / UPDATED
------------------------
src/department1/__init__.py
src/department1/pipeline.py
src/knowledge/source_recovery.py
src/knowledge/evaluator.py
run_department1.py
tests/test_department1_pipeline.py
tests/test_deep_knowledge_recovery.py

IMPORTANT ARCHITECTURE
----------------------
The new src/department1/pipeline.py is additive at this stage. It does NOT replace
app.py automatically.

This is deliberate:
- app.py still contains Departments 3-5 routing, publishing, caching and compatibility logic.
- We must not blindly overwrite that production orchestrator.
- First certify the corrected Department 1 behavior independently.
- Then wire app.py to the new Department1Pipeline in a controlled integration pass.

AUTHORITATIVE RULES
-------------------
1. Evaluator is strictly read-only.
2. Evaluator/recovery never writes canonical knowledge.
3. Pattern matches produce CANDIDATE or REVIEW_REQUIRED only.
4. Recovery candidates must pass the normal typed extraction, validation,
   conflict-resolution and fusion path before becoming canonical knowledge.
5. Completeness measures canonical representation of eligible source facts.
6. Generated output is never source evidence unless explicitly imported by the user.
7. Project corpus is defined by the explicit run manifest, not substring filename matching.
8. Project-folder namespace remains authoritative.

INSTALL
-------
Extract this ZIP over:

C:\Users\alits\instagram-agent

Before extraction, commit or back up the current project.

DEPENDENCIES
------------
python -m pip install --upgrade openai pymupdf python-docx

If external OpenAI processing is approved for Department 1 cognition:
D1_ALLOW_EXTERNAL_AI=true

OPTIONAL:
D1_MODEL=gpt-5

FOCUSED TESTS
-------------
python -m pytest -q tests/test_department1_pipeline.py tests/test_deep_knowledge_recovery.py tests/test_knowledge_evaluator.py

STANDALONE DEPARTMENT 1 TEST
----------------------------
python run_department1.py --project-root "input\Beverly Hills"

The canonical standalone handoff is written under:
output\department1\<project>\department2-handoff.json

FULL REGRESSION
---------------
After focused tests pass, run the project's complete existing test suite.

CERTIFICATION STATUS
--------------------
DO NOT FREEZE Department 1 yet.

This package fixes the four correctness defects and adds the explicit cognitive
pipeline, but automatic recovery orchestration back through the production typed
extraction/fusion path still requires final integration into the existing app
runtime before Department 1 can be certified.
