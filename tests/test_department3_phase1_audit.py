import json
from pathlib import Path
import tempfile
import unittest

from tools.department3_phase1_audit import run


class Department3Phase1AuditTests(unittest.TestCase):
    def _repo(self, td: str) -> Path:
        root = Path(td)
        (root / "src/creative").mkdir(parents=True)
        (root / "src/branding").mkdir(parents=True)
        (root / "src/execution").mkdir(parents=True)
        (root / "app.py").write_text(
            "from src.creative.visual_art_director import build\n"
            "from src.branding.composer import render\n",
            encoding="utf-8",
        )
        (root / "src/creative/visual_art_director.py").write_text(
            "def build(production_item_id):\n"
            "    contract_id = production_item_id\n"
            "    return {'contract_id': contract_id, 'production_item_id': production_item_id, 'visual_direction': {}}\n",
            encoding="utf-8",
        )
        (root / "src/creative/production_contract.py").write_text(
            "def sign(contract_id, production_item_id):\n"
            "    return f'{contract_id}:{production_item_id}'\n",
            encoding="utf-8",
        )
        (root / "src/branding/composer.py").write_text(
            "def render(vdc):\n"
            "    return vdc\n",
            encoding="utf-8",
        )
        return root

    def test_report_is_created(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            out = repo / "output/audits/department3"
            report = run(repo, out)
            self.assertTrue((out / "department3-phase1-authority-audit.json").is_file())
            self.assertTrue((out / "department3-phase1-authority-audit.md").is_file())
            self.assertGreaterEqual(report["summary"]["department3_files"], 2)

    def test_contract_binding_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            report = run(repo, repo / "out")
            codes = {f["code"] for f in report["findings"]}
            self.assertNotIn("D3-VDC-002", codes)


if __name__ == "__main__":
    unittest.main()
