import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.reset import ProjectResetError, reset_project_derived_state


def write(path: Path, value="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict): path.write_text(json.dumps(value), encoding="utf-8")
    else: path.write_text(value, encoding="utf-8")


class ProjectResetTests(unittest.TestCase):
    def fixture(self, root: Path):
        write(root/"input"/"Beverly Hills"/"source.txt", "source")
        write(root/"input"/"Other"/"source.txt", "other")
        write(root/"input"/"brand"/"logo.png", "brand")
        write(root/".env", "SECRET=x")
        for folder in ("knowledge","asset-intelligence","content","produced-images","post-packages","cache-metadata"):
            write(root/"output"/folder/("Beverly Hills" if folder in {"produced-images","cache-metadata"} else "Beverly Hills.json")/("item.png" if folder in {"produced-images","cache-metadata"} else "") if folder in {"produced-images","cache-metadata"} else root/"output"/folder/"Beverly Hills.json", {"project_id":"Beverly Hills"})
            write(root/"output"/folder/"Other.json", {"project_id":"Other"})
        state=root/"state"/"publishing";state.mkdir(parents=True)
        db=sqlite3.connect(state/"publication-ledger.sqlite3")
        db.executescript("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL); INSERT INTO metadata VALUES('schema_version','1'); CREATE TABLE publications(ledger_record_id TEXT PRIMARY KEY,publication_identity TEXT UNIQUE NOT NULL,semantic_creative_identity TEXT NOT NULL,project_id TEXT NOT NULL,platform TEXT NOT NULL,surface TEXT NOT NULL,format TEXT NOT NULL,package_id TEXT,production_contract_version TEXT,media_hashes_json TEXT NOT NULL,provenance_ids_json TEXT NOT NULL,caption_hash TEXT,payload_hash TEXT,account_id TEXT,remote_media_id TEXT,parent_container_id TEXT,child_container_ids_json TEXT NOT NULL,publication_timestamp TEXT,confirmation_timestamp TEXT,state TEXT NOT NULL,attempt_identity TEXT,receipt_id TEXT,receipt_version TEXT NOT NULL,created_at TEXT NOT NULL);")
        db.execute("INSERT INTO publications VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",("l1","pub1","creative1","Beverly Hills","Instagram","feed","single_image","pkg1","1",'[]','[]',None,"hash","ig","media1","container",'[]',"now","now","CONFIRMED_PUBLISHED","attempt","receipt1","1","now"));db.commit();db.close()
        write(root/"output"/"publishing"/"Beverly Hills-publication-manifest.json",{"project_id":"Beverly Hills","real_receipts":[{"receipt_id":"receipt1","status":"published","published_media_id":"media1","publication_identity":"pub1","idempotency_key":"pub1","package_id":"pkg1"}],"publication_history":[{"history_id":"h1","receipt_id":"receipt1","status":"published"}],"queue_items":[],"mock_receipts":[]})

    def test_dry_run_and_confirm_are_scoped_and_preserve_truth(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            before=(root/"input"/"Beverly Hills"/"source.txt").read_bytes()
            dry=reset_project_derived_state(root,"Beverly Hills")
            self.assertEqual(dry["mode"],"dry_run");self.assertTrue((root/"output"/"knowledge"/"Beverly Hills.json").exists())
            result=reset_project_derived_state(root,"Beverly Hills",confirm=True)
            self.assertEqual(result["status"],"completed");self.assertFalse((root/"output"/"knowledge"/"Beverly Hills.json").exists())
            self.assertTrue((root/"output"/"knowledge"/"Other.json").exists());self.assertEqual((root/"input"/"Beverly Hills"/"source.txt").read_bytes(),before)
            self.assertTrue((root/"input"/"brand"/"logo.png").exists());self.assertTrue((root/".env").exists())
            manifest=json.loads((root/"output"/"publishing"/"Beverly Hills-publication-manifest.json").read_text())
            self.assertEqual(manifest["real_receipts"][0]["published_media_id"],"media1")
            again=reset_project_derived_state(root,"Beverly Hills",confirm=True);self.assertEqual(again["status"],"completed")

    def test_wildcards_and_unknown_projects_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            with self.assertRaises(ProjectResetError):reset_project_derived_state(root,"*")
            with self.assertRaises(ProjectResetError):reset_project_derived_state(root,"Missing")


if __name__ == "__main__": unittest.main()
