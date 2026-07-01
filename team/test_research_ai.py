from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

from shared.ai.openrouter import OpenRouterClient, OpenRouterConfig
from team.research_ai import TEAM_RESEARCH_ANALYSIS_SCHEMA, TeamResearchAnalyzer, build_analysis_input, pdf_url_from_supported_link
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
            "abstract": "This paper studies tunable emissivity for switchable radiative cooling.",
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
            "relevance": "Relevant to dynamic radiative cooling.",
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
        "tags": ["Radiative Cooling", "#Tunable-Emissivity", "benchmark"],
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
            self.assertEqual(database.get_item_tags(item_id), ["benchmark", "radiative-cooling", "tunable-emissivity"])
            self.assertIn("Strong match", database.list_library("team-library")[0]["library_entry"]["reason"])
            self.assertEqual(database.list_latest_relevant_papers()[0]["ai_status"], "succeeded")

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

    def test_unsupported_non_pdf_link_records_pending_unsupported_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {"source_type": "url", "url": "https://example.org/paper-page"},
                analyze=False,
            )

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
