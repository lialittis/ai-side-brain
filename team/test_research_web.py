from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from team.research_db import TeamResearchDatabase
from team.research_web import (
    canonical_pdf_url,
    render_latest_papers_page,
    render_submit_page,
    parse_post_form,
    submit_research_item,
)


class TeamResearchWebTest(unittest.TestCase):
    def test_latest_and_submit_pages_have_simple_member_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            latest = render_latest_papers_page(database)
            submit = render_submit_page(database)

        self.assertIn("Latest Relevant Papers", latest)
        self.assertIn("No relevant papers yet", latest)
        self.assertIn("Submit To Library", submit)
        self.assertIn("Direct PDF link", submit)
        self.assertIn("PDF file", submit)
        self.assertIn("Manual link", submit)
        self.assertIn("Add PDF Link", submit)
        self.assertIn("Add PDF", submit)
        self.assertIn("Add Manual Link", submit)
        self.assertNotIn("Customized tags", submit)
        self.assertNotIn("Screening topic", submit)
        self.assertNotIn("Submitted by", submit)

    def test_manual_link_submission_creates_tagged_latest_relevant_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/paper",
                    "title": "Switchable radiative cooling envelope control",
                    "brief": (
                        "This study evaluates switchable radiative cooling with tunable emissivity. "
                        "It reports measured or simulated cooling performance and connects material "
                        "behavior to building or energy outcomes."
                    ),
                    "tags": "radiative-cooling, envelope",
                    "project": "dynamic-radiative-cooling",
                    "topic": "dynamic-radiative-cooling",
                    "submitted_by": "alice",
                    "year": "2026",
                },
                analyze=False,
            )

            papers = database.list_latest_relevant_papers()
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["item"]["id"], item_id)
            self.assertEqual(papers[0]["link"], "https://example.org/paper")
            self.assertEqual(papers[0]["tags"], ["envelope", "radiative-cooling"])
            self.assertEqual(database.list_latest_relevant_papers(tag="envelope")[0]["item"]["id"], item_id)
            self.assertEqual(database.find_item_by_url("https://example.org/paper")["id"], item_id)

            html = render_latest_papers_page(database)
            self.assertIn("Switchable radiative cooling envelope control", html)
            self.assertIn("radiative-cooling", html)
            self.assertIn("Open Link", html)

    def test_indirect_link_is_rejected_from_pdf_link_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with self.assertRaisesRegex(ValueError, "directly to a .pdf"):
                submit_research_item(
                    database,
                    {"source_type": "pdf_url", "url": "https://arxiv.org/abs/2511.18868v2"},
                )

    def test_direct_pdf_link_is_downloaded_saved_and_deduplicated_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            pdf_content = b"%PDF-1.4 downloaded paper content"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.download_direct_pdf", return_value=("paper.pdf", pdf_content)):
                    with mock.patch("team.research_web.analyze_submitted_item") as analyze:
                        first_id = submit_research_item(
                            database,
                            {"source_type": "pdf_url", "url": "https://example.org/papers/paper.pdf"},
                        )
                        duplicate_id = submit_research_item(
                            database,
                            {"source_type": "pdf_url", "url": "https://mirror.example.org/paper.pdf"},
                        )

            self.assertEqual(first_id, duplicate_id)
            self.assertEqual(analyze.call_count, 1)
            self.assertEqual(canonical_pdf_url("HTTPS://Example.org/papers/paper.pdf"), "https://example.org/papers/paper.pdf")
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)
            self.assertEqual(len(list(upload_dir.glob("*.pdf"))), 1)

    def test_manual_arxiv_link_is_canonicalized_and_deduplicated_without_pdf_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch("team.research_web.download_direct_pdf") as download:
                with mock.patch("team.research_web.analyze_submitted_item") as analyze:
                    first_id = submit_research_item(
                        database,
                        {
                            "source_type": "manual_link",
                            "url": "https://arxiv.org/abs/2511.18868v2",
                            "title": "KernelBand",
                            "brief": "Promising work on LLM-based kernel optimization.",
                        },
                    )
                    duplicate_id = submit_research_item(
                        database,
                        {
                            "source_type": "manual_link",
                            "url": "https://arxiv.org/pdf/2511.18868v1.pdf",
                            "title": "KernelBand mirror",
                            "brief": "Same paper from another arXiv URL form.",
                        },
                    )

            self.assertEqual(first_id, duplicate_id)
            self.assertEqual(analyze.call_count, 1)
            download.assert_not_called()
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)

    def test_legacy_url_source_is_treated_as_direct_pdf_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.download_direct_pdf", return_value=("paper.pdf", b"%PDF-1.4 url")):
                    item_id = submit_research_item(
                        database,
                        {"source_type": "url", "url": "https://example.org/paper.pdf"},
                        analyze=False,
                    )

            self.assertEqual(database.list_latest_relevant_papers()[0]["item"]["id"], item_id)

    def test_manual_link_requires_title_and_brief(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with self.assertRaisesRegex(ValueError, "brief info"):
                submit_research_item(
                    database,
                    {"source_type": "manual_link", "url": "https://example.org/promising"},
                )

    def test_pdf_submission_saves_file_and_lists_pdf_link(self) -> None:
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

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[0]["item"]["id"], item_id)
            self.assertEqual(papers[0]["item"]["title"], "paper")
            self.assertIn("paper.pdf", papers[0]["link"])
            self.assertTrue(Path(papers[0]["link"]).exists())
            self.assertEqual(papers[0]["tags"], [])
            self.assertTrue(list(upload_dir.glob("*.pdf")))
            self.assertIn("Open PDF", render_latest_papers_page(database))

    def test_duplicate_pdf_upload_reuses_existing_item_without_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            pdf_content = b"%PDF-1.4 same paper content"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.analyze_submitted_item") as analyze:
                    first_id = submit_research_item(
                        database,
                        {"source_type": "pdf_upload"},
                        upload=("paper-a.pdf", pdf_content),
                    )
                    duplicate_id = submit_research_item(
                        database,
                        {"source_type": "pdf_upload"},
                        upload=("paper-b.pdf", pdf_content),
                    )

            self.assertEqual(first_id, duplicate_id)
            self.assertEqual(analyze.call_count, 1)
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)
            self.assertEqual(len(list(upload_dir.glob("*.pdf"))), 1)

    def test_invalid_pdf_upload_is_rejected_before_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with self.assertRaisesRegex(ValueError, "not a valid PDF"):
                    submit_research_item(
                        database,
                        {"source_type": "pdf_upload"},
                        upload=("paper.pdf", b"not a pdf"),
                    )

            self.assertFalse(upload_dir.exists())
            self.assertEqual(database.list_latest_relevant_papers(), [])

    def test_link_only_submission_shows_even_when_screening_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.download_direct_pdf", return_value=("weak-metadata.pdf", b"%PDF-1.4 weak")):
                    item_id = submit_research_item(
                        database,
                        {
                            "source_type": "pdf_url",
                            "url": "https://example.org/papers/weak-metadata.pdf",
                        },
                        analyze=False,
                    )

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[0]["item"]["id"], item_id)
            self.assertEqual(papers[0]["item"]["title"], "weak metadata")
            self.assertEqual(papers[0]["screening"]["label"], "needs_review")
            self.assertEqual(papers[0]["tags"], [])

    def test_multipart_form_parser_extracts_fields_and_pdf(self) -> None:
        boundary = "sidebrainboundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="title"\r\n\r\n'
            "Multipart paper\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="pdf"; filename="paper.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
            "%PDF-1.4 parser test\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        handler = SimpleNamespace(headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

        fields, upload = parse_post_form(handler, body)

        self.assertEqual(fields["title"], "Multipart paper")
        self.assertEqual(upload, ("paper.pdf", b"%PDF-1.4 parser test"))


if __name__ == "__main__":
    unittest.main()
