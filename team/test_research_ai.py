from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from shared.ai.openrouter import OpenRouterClient, OpenRouterConfig
from shared.research import topic_profile_by_id
from team.research_adapter import build_team_research_run
from team.research_ai import (
    TEAM_RESEARCH_ANALYSIS_SCHEMA,
    TeamResearchAnalyzer,
    build_analysis_input,
    pdf_url_from_supported_link,
)
from team.research_db import TeamResearchDatabase
from team.research_web import submit_research_item


class FakeOpenRouterClient:
    def __init__(self, response: dict[str, object], model: str = "test/model") -> None:
        self.response = response
        self.config = SimpleNamespace(model=model)
        self.calls: list[dict[str, object]] = []

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.response


def ai_response() -> dict[str, object]:
    return {
        "document_classification": {
            "document_type": "research_paper",
            "is_research_paper": True,
            "rejection_reason": "",
        },
        "metadata": {
            "title": "AI analyzed tunable emissivity paper",
            "authors": ["Example Author"],
            "abstract": "This paper studies tunable emissivity for switchable radiative cooling and memory safety.",
            "year": 2026,
            "venue": "Example Journal",
            "identifiers": {"arxiv_id": "2605.14932"},
        },
        "research_card": {
            "research_question": "How does tunable emissivity improve cooling control?",
            "method": "experimental study",
            "data": "measurements described in the PDF",
            "findings": ["Tunable emissivity changes cooling performance."],
            "innovation": "Switchable envelope control.",
            "limitations": ["Small benchmark scope."],
            "relevance": "Relevant to memory safety evaluation.",
            "possible_use": ["benchmark"],
            "confidence": "high",
        },
        "relevance_screening": {
            "score": 88,
            "label": "highly_relevant",
            "reasons": ["Strong match to tunable emissivity and radiative cooling."],
            "matched_terms": ["tunable emissivity", "radiative cooling"],
            "suggested_contexts": ["dynamic-radiative-cooling"],
            "suggested_actions": ["add_to_project_review:dynamic-radiative-cooling"],
            "confidence": "high",
        },
        "tags": ["Radiative Cooling", "#Tunable-Emissivity", "Memory Safety", "benchmark"],
    }


def non_paper_response() -> dict[str, object]:
    response = ai_response()
    response["document_classification"] = {
        "document_type": "non_paper",
        "is_research_paper": False,
        "rejection_reason": "The PDF is a product brochure, not a research paper.",
    }
    response["metadata"] = {
        "title": "Cooling product brochure",
        "authors": [],
        "abstract": "",
        "year": None,
        "venue": None,
        "identifiers": {
            "doi": None,
            "arxiv_id": None,
            "pmid": None,
            "semantic_scholar_id": None,
            "openalex_id": None,
        },
    }
    response["tags"] = ["brochure"]
    return response


class TeamResearchAITest(unittest.TestCase):
    def test_analysis_schema_uses_strict_fixed_identifier_fields(self) -> None:
        identifiers = TEAM_RESEARCH_ANALYSIS_SCHEMA["properties"]["metadata"]["properties"]["identifiers"]

        self.assertFalse(identifiers["additionalProperties"])
        self.assertEqual(set(identifiers["required"]), set(identifiers["properties"]))
        self.assertEqual(identifiers["properties"]["arxiv_id"]["type"], ["string", "null"])
        self.assertIn("document_classification", TEAM_RESEARCH_ANALYSIS_SCHEMA["required"])

    def test_successful_pdf_analysis_updates_item_card_screening_tags_and_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                item_id = submit_research_item(
                    database,
                    {"source_type": "pdf_upload"},
                    upload=("paper.pdf", b"%PDF-1.4 test content"),
                    analyze=False,
                )

            client = FakeOpenRouterClient(ai_response())
            with mock.patch.dict("os.environ", {"SIDE_BRAIN_OPENROUTER_PDF_ENGINE": "native"}):
                run = TeamResearchAnalyzer(database, client=client).analyze_item(item_id)

            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(client.calls[0]["plugins"], [{"id": "file-parser", "pdf": {"engine": "native"}}])
            self.assertIn("topic_profile", json.dumps(client.calls[0]["messages"]))
            bundle = database.get_bundle(item_id)
            self.assertEqual(bundle["item"]["title"], "AI analyzed tunable emissivity paper")
            self.assertEqual(bundle["card"]["ai_model_used"], "test/model")
            self.assertEqual(bundle["screening"]["label"], "highly_relevant")
            self.assertEqual(
                database.get_item_tags(item_id),
                ["benchmark", "memory-safety", "radiative-cooling", "tunable-emissivity"],
            )
            self.assertEqual(
                [record["tag"] for record in database.list_tag_catalog()],
                ["benchmark", "memory-safety", "radiative-cooling", "tunable-emissivity"],
            )
            self.assertIn("memory safety", database.list_library("team-library")[0]["library_entry"]["reason"])
            self.assertEqual(database.list_latest_relevant_papers()[0]["ai_status"], "succeeded")

    def test_ai_prefers_tag_catalog_and_limits_new_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            database.ensure_tag_catalog(["memory-safety", "system-security", "agentic-security"], source="curated")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/catalog-tags",
                    "title": "Catalog Tags",
                    "brief": "Memory safety and agentic security for system security.",
                },
                analyze=False,
            )
            response = ai_response()
            response["tags"] = [
                "Memory Safety",
                "System Security",
                "Agentic Security",
                "Novel Tag A",
                "Novel Tag B",
                "Novel Tag C",
            ]

            client = FakeOpenRouterClient(response)
            run = TeamResearchAnalyzer(database, client=client).analyze_item(item_id)

            self.assertEqual(run["status"], "succeeded")
            prompt = json.dumps(client.calls[0]["messages"])
            self.assertIn("tag_catalog", prompt)
            self.assertIn("memory-safety", prompt)
            self.assertEqual(
                database.get_item_tags(item_id),
                ["agentic-security", "memory-safety", "novel-tag-a", "novel-tag-b", "system-security"],
            )
            catalog_tags = [record["tag"] for record in database.list_tag_catalog()]
            self.assertIn("novel-tag-a", catalog_tags)
            self.assertIn("novel-tag-b", catalog_tags)
            self.assertNotIn("novel-tag-c", catalog_tags)

    def test_ai_analysis_preserves_manual_relevance_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/manual-override",
                    "title": "Manual Override Paper",
                    "brief": "This paper mentions memory safety.",
                },
                analyze=False,
            )
            database.update_item_relevance(item_id, label="low_relevance", score=5)

            run = TeamResearchAnalyzer(database, client=FakeOpenRouterClient(ai_response())).analyze_item(item_id)

            self.assertEqual(run["status"], "succeeded")
            screening = database.get_bundle(item_id)["screening"]
            self.assertEqual(screening["label"], "low_relevance")
            self.assertEqual(screening["score"], 5.0)
            self.assertTrue(screening["source_trace"]["manual_override"])

    def test_missing_api_key_records_pending_without_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                item_id = submit_research_item(
                    database,
                    {"source_type": "pdf_upload"},
                    upload=("paper.pdf", b"%PDF-1.4 test content"),
                    analyze=False,
                )

            client = OpenRouterClient(OpenRouterConfig(api_key=None, model="test/model"))
            run = TeamResearchAnalyzer(database, client=client).analyze_item(item_id)

            self.assertEqual(run["status"], "pending")
            self.assertIn("OPENROUTER_API_KEY", run["error"])
            self.assertEqual(database.list_latest_relevant_papers()[0]["ai_status"], "pending")

    def test_analyze_pending_reuses_existing_pending_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                item_id = submit_research_item(
                    database,
                    {"source_type": "pdf_upload"},
                    upload=("paper.pdf", b"%PDF-1.4 test content"),
                    analyze=False,
                )

            no_key_client = OpenRouterClient(OpenRouterConfig(api_key=None, model="test/model"))
            pending_run = TeamResearchAnalyzer(database, client=no_key_client).analyze_item(item_id)
            runs = TeamResearchAnalyzer(database, client=FakeOpenRouterClient(ai_response())).analyze_pending()

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["id"], pending_run["id"])
            self.assertEqual(runs[0]["status"], "succeeded")
            self.assertEqual(database.list_ai_analysis_runs(statuses=("pending",)), [])
            succeeded_runs = database.list_ai_analysis_runs(statuses=("succeeded",), limit=10)
            self.assertEqual([run["id"] for run in succeeded_runs], [pending_run["id"]])

    def test_non_paper_pdf_is_archived_without_latest_paper_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                item_id = submit_research_item(
                    database,
                    {"source_type": "pdf_upload"},
                    upload=("brochure.pdf", b"%PDF-1.4 product brochure"),
                    analyze=False,
                )

            run = TeamResearchAnalyzer(database, client=FakeOpenRouterClient(non_paper_response())).analyze_item(item_id)

            self.assertEqual(run["status"], "rejected_non_paper")
            self.assertIn("product brochure", run["error"])
            bundle = database.get_bundle(item_id)
            self.assertEqual(bundle["item"]["item_type"], "other")
            self.assertEqual(bundle["team_record"]["review_status"], "rejected")
            self.assertEqual(bundle["library_entries"][0]["status"], "archived")
            self.assertEqual(bundle["screening"]["label"], "low_relevance")
            self.assertEqual(database.list_latest_relevant_papers(), [])

    def test_manual_link_analysis_uses_text_only_without_pdf_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/promising-work",
                    "title": "Promising Work",
                    "brief": "A promising work mentioned in a seminar, but no direct PDF is available.",
                },
                analyze=False,
            )

            client = FakeOpenRouterClient(ai_response())
            run = TeamResearchAnalyzer(database, client=client).analyze_item(item_id)

            self.assertEqual(run["status"], "succeeded")
            self.assertIsNone(client.calls[0]["plugins"])
            self.assertNotIn('"type": "file"', json.dumps(client.calls[0]["messages"]))

    def test_legacy_unsupported_non_pdf_link_records_pending_unsupported_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            result = build_team_research_run(
                source_type="url",
                source_value="https://example.org/paper-page",
                metadata={
                    "title": "Legacy page",
                    "abstract": "",
                    "authors": [],
                    "item_type": "paper",
                    "url": "https://example.org/paper-page",
                },
                topic_profile=topic_profile_by_id("dynamic-radiative-cooling"),
                project_id="team-library",
                submitted_by="test",
            )
            database.write_run(result, include_library_entry=False)

            item_id = result.item["id"]
            run = TeamResearchAnalyzer(database, client=FakeOpenRouterClient(ai_response())).analyze_item(item_id)

            self.assertEqual(run["status"], "pending_unsupported_link")
            self.assertIn("Only uploaded PDFs", run["error"])

    def test_arxiv_abs_link_is_converted_to_pdf_input(self) -> None:
        self.assertEqual(
            pdf_url_from_supported_link("https://arxiv.org/abs/2605.14932v1"),
            "https://arxiv.org/pdf/2605.14932v1.pdf",
        )
        analysis_input = build_analysis_input({"url": "https://arxiv.org/abs/2605.14932v1"})
        self.assertTrue(analysis_input.supported)
        self.assertEqual(analysis_input.file_data, "https://arxiv.org/pdf/2605.14932v1.pdf")


if __name__ == "__main__":
    unittest.main()
