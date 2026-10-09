"""Department 4 adversarial freeze probes (40 independently reported cases)."""

from __future__ import annotations

from copy import deepcopy
import tempfile
from pathlib import Path
import unittest

from PIL import Image

from src.creative.production_contract import validate_project_context, validate_publication_package


class Department4ProductionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.image = Path(self.tmp.name) / "feed.png"
        Image.new("RGB", (1080, 1350), "white").save(self.image)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def package(self) -> dict:
        return {
            "project_id": "Project A", "package_type": "single_post", "platform": "Instagram Feed",
            "language_code": "en", "caption": {"project_id": "Project A", "text_direction": "ltr", "full_caption": "A verified project view."},
            "image": {"branded_item_id": "b1", "provenance_id": "p1", "source_asset_ids": ["a1"], "image_path": str(self.image)},
        }


def _package_probe(index: int, mutation) -> None:
    def test(self: Department4ProductionContractTests) -> None:
        package = self.package()
        mutation(self, package)
        self.assertTrue(validate_publication_package(package, expected_project="Project A"))
    setattr(Department4ProductionContractTests, f"test_adversarial_{index:02d}", test)


def _set(path: tuple[str, ...], value):
    def mutate(_self, package):
        target = package
        for key in path[:-1]: target = target[key]
        target[path[-1]] = value
    return mutate


_MUTATIONS = [
    _set(("project_id",), "Project B"),
    _set(("caption", "project_id"), "Project B"),
    _set(("language_code",), "fr"),
    _set(("language_code",), ""),
    _set(("caption", "text_direction"), "rtl"),
    _set(("caption", "text_direction"), ""),
    _set(("caption", "full_caption"), "Guaranteed return."),
    _set(("caption", "full_caption"), "High ROI."),
    _set(("caption", "full_caption"), "Rental yield opportunity."),
    _set(("caption", "full_caption"), "Best investment."),
    _set(("caption", "full_caption"), "Limited time."),
    _set(("caption", "full_caption"), "Last chance."),
    _set(("caption", "full_caption"), "Selling fast."),
    _set(("caption", "full_caption"), "Scarcity creates value."),
    _set(("caption", "full_caption"), "Price available now."),
    _set(("caption", "full_caption"), "Payment plan available."),
    _set(("caption", "full_caption"), "Special discount."),
    _set(("caption", "full_caption"), "Availability is limited."),
    _set(("image", "branded_item_id"), ""),
    _set(("image", "provenance_id"), ""),
    _set(("image", "source_asset_ids"), []),
    _set(("image", "source_asset_ids"), None),
    _set(("image", "image_path"), "missing.png"),
    _set(("image", "image_path"), ""),
    lambda self, p: p.update(image=[]),
    lambda self, p: p.update(image=None),
    lambda self, p: p.update(package_type="carousel", slides=[]),
    lambda self, p: p.update(package_type="carousel", slides=[{**deepcopy(p["image"]), "slide_number": 2}]),
    lambda self, p: p.update(package_type="carousel", slides=[{**deepcopy(p["image"]), "slide_number": 1}, {**deepcopy(p["image"]), "slide_number": 3}]),
    lambda self, p: p.update(package_type="carousel", slides=[{**deepcopy(p["image"]), "slide_number": 1}, {**deepcopy(p["image"]), "slide_number": 1}]),
    lambda self, p: p.update(language_code="ar", caption={**p["caption"], "text_direction": "ltr"}),
    lambda self, p: p.update(language_code="ku", caption={**p["caption"], "text_direction": "ltr"}),
    lambda self, p: p.update(language_code="ar", caption={**p["caption"], "text_direction": ""}),
    lambda self, p: p.update(language_code="ku", caption={**p["caption"], "text_direction": ""}),
    lambda self, p: (Image.new("RGB", (1080, 1080), "white").save(self.image), p.update(platform="Instagram Feed Portrait")),
    lambda self, p: (Image.new("RGB", (1080, 1920), "white").save(self.image), p.update(platform="Instagram Feed")),
    lambda self, p: (Image.new("RGB", (1080, 1350), "white").save(self.image), p.update(platform="Instagram Story")),
    lambda self, p: (Image.new("RGB", (900, 1600), "white").save(self.image), p.update(platform="Instagram Story")),
    lambda self, p: (Image.new("RGB", (1200, 1500), "white").save(self.image)),
    lambda self, p: (Image.new("RGB", (1, 1), "white").save(self.image)),
]

for _index, _mutation in enumerate(_MUTATIONS, 1):
    _package_probe(_index, _mutation)


class Department4ProjectContextTests(unittest.TestCase):
    def test_project_context_accepts_matching_and_unlabelled_support(self) -> None:
        validate_project_context("A", {"one": {"project_id": "A"}, "brand": {}})

    def test_project_context_rejects_foreign_project_id(self) -> None:
        with self.assertRaises(ValueError): validate_project_context("A", {"manifest": {"project_id": "B"}})

    def test_project_context_rejects_foreign_project_alias(self) -> None:
        with self.assertRaises(ValueError): validate_project_context("A", {"inventory": {"project": "B"}})


if __name__ == "__main__":
    unittest.main()
