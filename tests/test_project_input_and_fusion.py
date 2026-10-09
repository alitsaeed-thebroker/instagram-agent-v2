"""Tests for multi-document project discovery, classification, and fusion."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.file_manager import find_project_inputs
from src.knowledge.document_classifier import DocumentClassifier, DocumentType
from src.knowledge.fusion import fuse_knowledge
from src.knowledge.schema import Pricing, ProjectDetails, ProjectKnowledge


class ProjectInputTests(unittest.TestCase):
    def test_branding_only_is_workspace_configuration_not_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            logo = root / "brand/logos/company.png"
            logo.parent.mkdir(parents=True)
            logo.touch()
            projects = find_project_inputs(root)
        self.assertTrue(logo.parent.name == "logos")
        self.assertEqual(projects, [])

    def test_publishing_configuration_only_is_not_a_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "publishing/meta-config.json"
            config.parent.mkdir(parents=True)
            config.write_text("{}", encoding="utf-8")
            projects = find_project_inputs(root)
        self.assertEqual(projects, [])

    def test_branding_and_publishing_configuration_do_not_create_projects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "brand/logos").mkdir(parents=True)
            (root / "brand/logos/company.webp").touch()
            (root / "publishing").mkdir()
            (root / "publishing/publishing-config.json").write_text("{}", encoding="utf-8")
            projects = find_project_inputs(root)
        self.assertEqual(projects, [])

    def test_project_pdf_does_not_inherit_workspace_brand_visuals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "project.pdf").touch()
            (root / "brand/logos").mkdir(parents=True)
            logo = root / "brand/logos/company.png"
            logo.touch()
            with patch("src.core.file_manager._project_identity_from_pdf", return_value="Project One"):
                projects = find_project_inputs(root)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].image_files, [])
        self.assertNotIn(logo, projects[0].image_files)

    def test_project_image_is_included_but_workspace_brand_visual_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "project.pdf").touch()
            project_image = root / "project-exterior.jpg"
            project_image.touch()
            (root / "brand/logos").mkdir(parents=True)
            logo = root / "brand/logos/company.jpg"
            logo.touch()
            with patch("src.core.file_manager._project_identity_from_pdf", return_value="Project One"):
                projects = find_project_inputs(root)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].image_files, [project_image])
        self.assertNotIn(logo, projects[0].image_files)

    def test_multiple_projects_never_receive_workspace_brand_visuals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "first.pdf", root / "second.pdf"
            first.touch(); second.touch()
            (root / "brand/logos").mkdir(parents=True)
            logo = root / "brand/logos/company.png"
            logo.touch()
            identities = {"first.pdf": "First", "second.pdf": "Second"}
            with patch("src.core.file_manager._project_identity_from_pdf", side_effect=lambda path: identities[path.name]):
                projects = find_project_inputs(root)
        self.assertEqual({project.name for project in projects}, {"First", "Second"})
        self.assertTrue(all(logo not in project.image_files for project in projects))

    def test_one_project_with_one_pdf_uses_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Beverly Hills.pdf").touch()
            with patch("src.core.file_manager._project_identity_from_pdf", return_value="Beverly Hills"):
                projects = find_project_inputs(root)
        self.assertEqual([(project.name, len(project.pdf_files)) for project in projects], [("Beverly Hills", 1)])

    def test_one_project_with_multiple_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "Beverly Hills"
            project.mkdir()
            (project / "Catalogue.pdf").touch()
            (project / "Price List.pdf").touch()
            with patch("src.core.file_manager._project_identity_from_pdf", return_value="Beverly Hills"):
                projects = find_project_inputs(Path(directory))
        self.assertEqual(projects[0].name, "Beverly Hills")
        self.assertEqual([path.name for path in projects[0].pdf_files], ["Catalogue.pdf", "Price List.pdf"])

    def test_folder_is_namespace_even_when_pdf_text_is_page_numbers(self)->None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/"Stable Project";folder.mkdir();pdf=folder/"catalog.pdf";pdf.touch()
            with patch("src.core.file_manager._project_identity_from_pdf",return_value="2 3"):projects=find_project_inputs(root)
        self.assertEqual(projects[0].name,"Stable Project")

    def test_two_folder_namespaces_are_isolated_and_generic_headings_ignored(self)->None:
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ("Project Alpha","Project Beta"):(root/name).mkdir();(root/name/"catalog.pdf").touch()
            with patch("src.core.file_manager._project_identity_from_pdf",return_value="CONTENTS"):projects=find_project_inputs(root)
        self.assertEqual({x.name for x in projects},{"Project Alpha","Project Beta"});self.assertTrue(all(len(x.pdf_files)==1 for x in projects))

    def test_empty_project_folder_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "Empty Project").mkdir()
            projects = find_project_inputs(Path(directory))
        self.assertEqual(projects, [])

    def test_mixed_projects_are_kept_separate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "Beverly Hills"
            folder.mkdir()
            (folder / "Catalogue.pdf").touch()
            (root / "Palm Gardens.pdf").touch()
            identities = {"Catalogue.pdf": "Beverly Hills", "Palm Gardens.pdf": "Palm Gardens"}
            with patch("src.core.file_manager._project_identity_from_pdf", side_effect=lambda path: identities[path.name]):
                projects = find_project_inputs(root)
        self.assertEqual({project.name: len(project.pdf_files) for project in projects}, {"Beverly Hills": 1, "Palm Gardens": 1})

    def test_conflicting_filenames_cannot_split_same_content_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Project Alpha.pdf").touch()
            (root / "Completely Different Name.pdf").touch()
            with patch("src.core.file_manager._project_identity_from_pdf", return_value="Content Project"):
                projects = find_project_inputs(root)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0].name, "Content Project")
        self.assertEqual(len(projects[0].pdf_files), 2)

    def test_missing_content_identity_is_retained_as_ambiguous_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Very Convincing Project Name.pdf").touch()
            with patch("src.core.file_manager._project_identity_from_pdf", return_value=None):
                projects = find_project_inputs(root)
        self.assertEqual(projects[0].name, "project-candidate-001")
        self.assertTrue(projects[0].warnings)

    def test_project_folders_own_local_images_and_auxiliary_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_a = root / "Project A"
            project_b = root / "Project B"
            shared = root / "brand"
            project_a.mkdir(); project_b.mkdir(); shared.mkdir()
            for name in ("catalogue.pdf", "renders.pdf", "price-list.pdf"):
                (project_a / name).touch()
            (project_a / "brochure-image.jpg").touch()
            (project_a / "project-notes.txt").touch()
            (project_b / "masterplan.pdf").touch()
            (project_b / "pricing.docx").touch()
            (project_b / "exterior.png").touch()
            (shared / "Domus logo.png").touch()
            (shared / "company-brand-guidelines.pdf").touch()
            identities = {
                "catalogue.pdf": "Project A", "renders.pdf": "Project A",
                "price-list.pdf": "Project A", "masterplan.pdf": "Project B",
            }
            with patch("src.core.file_manager._project_identity_from_pdf", side_effect=lambda path: identities[path.name]):
                projects = find_project_inputs(root)

        indexed = {project.name: project for project in projects}
        self.assertEqual(set(indexed), {"Project A", "Project B"})
        self.assertEqual({path.name for path in indexed["Project A"].pdf_files}, {"catalogue.pdf", "renders.pdf", "price-list.pdf"})
        self.assertEqual([path.name for path in indexed["Project A"].image_files], ["brochure-image.jpg"])
        self.assertEqual([path.name for path in indexed["Project A"].auxiliary_files], ["project-notes.txt"])
        self.assertEqual([path.name for path in indexed["Project B"].pdf_files], ["masterplan.pdf"])
        self.assertEqual([path.name for path in indexed["Project B"].image_files], ["exterior.png"])
        self.assertEqual([path.name for path in indexed["Project B"].auxiliary_files], ["pricing.docx"])


class DocumentFusionTests(unittest.TestCase):
    def test_missing_document_types_classify_as_other(self) -> None:
        classifier = DocumentClassifier(ai_classifier=lambda *_: None)
        self.assertEqual(classifier.classify("notes.pdf", "miscellaneous notes").document_type, DocumentType.OTHER)

    def test_conflicting_information_uses_higher_confidence_document(self) -> None:
        catalogue = ProjectKnowledge(project=ProjectDetails(name="Beverly Hills", location="Baghdad"), pricing=Pricing(currency="USD", starting_price=100000))
        price_list = ProjectKnowledge(project=ProjectDetails(name="Beverly Hills", location="Baghdad"), pricing=Pricing(currency="USD", starting_price=125000))
        merged, conflicts = fuse_knowledge([
            (catalogue, DocumentType.CATALOGUE, Path("Catalogue.json")),
            (price_list, DocumentType.PRICE_LIST, Path("Price List.json")),
        ])
        self.assertEqual(merged.pricing.starting_price, 125000)
        self.assertTrue(conflicts)
