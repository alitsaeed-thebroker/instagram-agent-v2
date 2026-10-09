import json
import tempfile
import unittest
from pathlib import Path

from tools.department3_phase2_behavioral_classification import SourceIndex, classify_one


class Department3Phase2ClassificationTests(unittest.TestCase):
    def test_d4_vdc_execution_is_not_automatically_called_bypass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "src/branding"
            p.mkdir(parents=True)
            (p / "composer.py").write_text(
                "def compose(vdc):\n"
                "    layout = vdc['visual_direction']['layout']\n"
                "    return render(layout)\n",
                encoding="utf-8",
            )
            idx = SourceIndex(root)
            c = classify_one(idx, {
                "file": "src/branding/composer.py",
                "line": 2,
                "code": "D3-AUTH-201",
                "evidence": "term='layout'",
            })
            self.assertNotEqual(c.classification, "UNAUTHORIZED_CREATIVE_AUTHORITY")

    def test_random_d4_creative_choice_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = root / "src/branding"
            p.mkdir(parents=True)
            (p / "composer.py").write_text(
                "import random\n"
                "def compose(vdc):\n"
                "    layout = random.choice(['left','right'])\n"
                "    return layout\n",
                encoding="utf-8",
            )
            idx = SourceIndex(root)
            c = classify_one(idx, {
                "file": "src/branding/composer.py",
                "line": 3,
                "code": "D3-AUTH-201",
                "evidence": "term='layout'",
            })
            self.assertEqual(c.classification, "UNAUTHORIZED_CREATIVE_AUTHORITY")


if __name__ == "__main__":
    unittest.main()
