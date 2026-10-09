"""Adversarial tests for recovery: fail closed without cross-project evidence."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from src.knowledge.document_classifier import DocumentClassifier, DocumentType
from src.knowledge.handoff import load_department2_handoff, Department2HandoffError, _payload_hash
from src.department1.pipeline import Department1Pipeline, Department1Config, project_storage_key
from src.hardening.pipeline import _source_hashes
from src.knowledge.source_recovery import _corpus
from tests.test_department2_handoff import FakeClient

class RecoveryTests(unittest.TestCase):
    def test_downstream_cache_includes_changed_scenes_and_shots(self):
        import app
        class Captured(Exception):pass
        captured=[]
        class Cache:
            def expected(self,stage,inputs,**kwargs):captured.append((stage,inputs));raise Captured()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);knowledge=root/"knowledge.json";inventory=root/"inventory.json";content=root/"content.json";source=root/"manifest.json"
            for p in (knowledge,inventory,content,source):p.write_text('{}')
            artifacts={'-creative-directions':root/'creative.json','-scene-plans':root/'scenes.json','-shot-plans':root/'shots.json'}
            with patch.object(app,'PROJECT_ROOT',root),patch.object(app,'_artifact',side_effect=lambda directory,project,suffix:artifacts.get(suffix)):
                for stage in ('scene-planner','shot-planner','image-processing-planner'):
                    with self.assertRaises(Captured):app._run_downstream_stage(stage,'Beverly Hills',{'content_plan':content},knowledge,knowledge,inventory,source,Cache(),None)
            inputs=dict(captured)
            self.assertIn(artifacts['-creative-directions'],inputs['scene-planner'])
            self.assertIn(root/'input/visual-review/project-overview-reviews.json',inputs['scene-planner'])
            self.assertIn(artifacts['-scene-plans'],inputs['shot-planner'])
            self.assertIn(artifacts['-shot-plans'],inputs['image-processing-planner'])
            self.assertIn(source,inputs['image-processing-planner'])

    def test_invalid_ai_json_is_auditable_unknown_and_empty_content_makes_no_call(self):
        def invalid(*args):raise json.JSONDecodeError("secret service content", "private", 0)
        result=DocumentClassifier(ai_classifier=invalid).classify("Catalogue.pdf", "unclassified evidence")
        self.assertEqual(result.document_type,DocumentType.UNKNOWN)
        self.assertEqual(result.to_dict()["fallback_error"],"JSONDecodeError")
        self.assertNotIn("secret",str(result.to_dict()))
        self.assertIsNone(DocumentClassifier(ai_classifier=invalid).classify("Catalogue.pdf", "").fallback_error)

    def test_real_ai_adapter_requests_structured_json_and_rejects_invented_evidence(self):
        calls=[]
        payload={"classification":"Catalogue","confidence":.9,"evidence":["invented fact"],"roles":[]}
        client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kw:(calls.append(kw) or SimpleNamespace(output_text=json.dumps(payload)))))
        with patch("openai.OpenAI",return_value=client),patch.dict("os.environ",{"OPENAI_API_KEY":"fixture"}):
            result=DocumentClassifier().classify("Price List.pdf","unclassified evidence")
        self.assertEqual(result.document_type,DocumentType.UNKNOWN)
        self.assertEqual(result.fallback_error,"ValueError")
        self.assertEqual(calls[0]["text"]["format"]["type"],"json_schema")

    def build(self,root):
        project=root/"input"/"A";project.mkdir(parents=True)
        source=project/"a.txt";source.write_text("A evidence")
        out=root/"out"
        payload=Department1Pipeline(project,output_root=out,config=Department1Config(allow_external_ai=True),client=FakeClient()).run()
        path=out/project_storage_key("A")/"department2-handoff.json"
        return project,source,payload,path

    def test_added_source_and_missing_source_record_invalidate_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            project,source,payload,path=self.build(Path(td))
            added=project/"new.txt";added.write_text("new evidence")
            with self.assertRaises(Department2HandoffError):load_department2_handoff(path,expected_project="A",project_root=project,source_paths=[source,added])
            payload["source_hashes"]["unrecorded.txt"]="a"*64;payload["handoff_sha256"]=_payload_hash(payload);path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(Department2HandoffError,"inventory differ"):load_department2_handoff(path,expected_project="A",project_root=project)

    def test_source_block_path_must_match_exact_source_record(self):
        with tempfile.TemporaryDirectory() as td:
            project,source,payload,path=self.build(Path(td))
            payload["sources"][0]["blocks"][0]["provenance"]["source_file"]="neighbor.txt"
            payload["handoff_sha256"]=_payload_hash(payload);path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(Department2HandoffError,"source path mismatch"):load_department2_handoff(path,expected_project="A",project_root=project)

    def test_release_manifest_hashes_only_exact_project_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"input"
            for folder in ("A","A Residences","editorial-copy","campaigns"):
                p=root/folder/"notes.txt";p.parent.mkdir(parents=True);p.write_text(folder)
            self.assertEqual(set(_source_hashes(root,"A")),{str((root/"A/notes.txt").resolve())})

    def test_foreign_manifest_source_is_rejected_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/"input/A").mkdir(parents=True)
            foreign=root/"input/A Residences/notes.txt";foreign.parent.mkdir();foreign.write_text("Starting price USD 777777")
            manifest=root/"output/manifests/A-run-manifest.json";manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"project_id":"A","source_file_hashes":{str(foreign):hashlib.sha256(foreign.read_bytes()).hexdigest()}}))
            blocks,errors,audit=_corpus(root,"A",root/"output/knowledge/A.json")
            self.assertEqual(blocks,[]);self.assertEqual(errors[0]["classification"],"PROJECT_SOURCE_SCOPE_MISMATCH")

if __name__=="__main__":unittest.main()
