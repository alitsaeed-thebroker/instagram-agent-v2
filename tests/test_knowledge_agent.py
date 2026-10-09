"""Unit tests for the Markdown-to-knowledge agent without API calls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.ai.agents.knowledge_agent import KnowledgeAgent
from src.knowledge.schema import ProjectDetails, ProjectKnowledge


class KnowledgeAgentTests(unittest.TestCase):
    def test_run_saves_valid_api_response(self) -> None:
        response = ProjectKnowledge(project=ProjectDetails(name="Palm Gardens", location="Baghdad")).to_json()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalogue.md"
            source.write_text("# Palm Gardens", encoding="utf-8")
            output_directory = Path(directory) / "knowledge"
            agent = KnowledgeAgent(model="test-model")
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_knowledge", return_value=response),
                patch("src.ai.agents.knowledge_agent.save_project_knowledge") as save,
            ):
                save.side_effect = lambda knowledge, filename: _save(knowledge, filename, output_directory)
                path = agent.run(source)
                self.assertEqual(path.name, "palm-gardens.json")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["project"]["name"], "Palm Gardens")

    def test_run_rejects_invalid_api_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "catalogue.md"
            source.write_text("# Catalogue", encoding="utf-8")
            agent = KnowledgeAgent()
            with (
                patch.object(agent, "_load_api_key", return_value="test-key"),
                patch.object(agent, "_request_knowledge", return_value="not json"),
            ):
                self.assertIsNone(agent.run(source))


def _save(knowledge: ProjectKnowledge, filename: str, directory: Path) -> Path:
    directory.mkdir()
    path = directory / f"{filename}.json"
    path.write_text(knowledge.to_json(), encoding="utf-8")
    return path
