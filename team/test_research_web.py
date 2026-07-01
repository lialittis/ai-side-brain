from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from team.research_db import TeamResearchDatabase
from team.research_web import (
    add_paper_tag,
    canonical_pdf_url,
    render_latest_papers_page,
    render_submit_page,
    parse_post_form,
    recover_paper,
    remove_paper,
    remove_paper_tag,
    submit_research_item,
    update_paper_tag,
    update_paper_importance,
    update_paper_interactions,
    update_paper_relevance,
    update_paper_tags,
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

    def test_paper_interactions_update_tags_relevance_and_importance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/interaction",
                    "title": "Interaction Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )

            update_paper_interactions(
                database,
                {
                    "item_id": item_id,
                    "tags": "priority, #cooling",
                    "relevance_label": "highly_relevant",
                    "relevance_score": "94",
                    "importance": "5",
                },
            )

            paper = database.list_latest_relevant_papers(sort_by="importance")[0]
            self.assertEqual(paper["tags"], ["cooling", "priority"])
            self.assertEqual(paper["screening"]["label"], "highly_relevant")
            self.assertEqual(paper["screening"]["score"], 94.0)
            self.assertEqual(paper["importance"], 5)

            html = render_latest_papers_page(database)
            self.assertIn("class=\"tag-chip-form\"", html)
            self.assertIn("class=\"tag-chip-input\"", html)
            self.assertIn("class=\"tag-add-form\"", html)
            self.assertIn("class=\"paper-footer\"", html)
            self.assertIn("class=\"paper-controls\"", html)
            self.assertIn("class=\"paper-actions\"", html)
            self.assertIn("name=\"importance\"", html)
            self.assertIn("name=\"relevance_label\"", html)
            self.assertIn("class=\"pill-select\"", html)
            self.assertIn("onchange=\"this.form.submit()\"", html)
            self.assertIn("Remove", html)
            self.assertNotIn("class=\"tag-input\"", html)
            self.assertNotIn("paper-editor", html)

    def test_direct_component_updates_can_save_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/direct-components",
                    "title": "Direct Components",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )

            update_paper_tags(database, {"item_id": item_id, "tags": "first, second"})
            update_paper_tag(database, {"item_id": item_id, "old_tag": "first", "tag": "renamed"})
            remove_paper_tag(database, {"item_id": item_id, "old_tag": "second"})
            add_paper_tag(database, {"item_id": item_id, "tag": "third"})
            update_paper_relevance(
                database,
                {
                    "item_id": item_id,
                    "relevance_label": "highly_relevant",
                    "relevance_score": "82",
                },
            )
            update_paper_importance(database, {"item_id": item_id, "importance": "4"})

            paper = database.list_latest_relevant_papers()[0]
            self.assertEqual(paper["tags"], ["renamed", "third"])
            self.assertEqual(paper["screening"]["label"], "highly_relevant")
            self.assertEqual(paper["screening"]["score"], 82.0)
            self.assertEqual(paper["importance"], 4)

    def test_papers_can_be_sorted_by_name_publish_date_relevance_and_importance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            alpha_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/alpha",
                    "title": "Alpha Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                    "year": "2024",
                },
                analyze=False,
            )
            zeta_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/zeta",
                    "title": "Zeta Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                    "year": "2026",
                },
                analyze=False,
            )
            database.update_item_relevance(alpha_id, label="possibly_relevant", score=40)
            database.update_item_relevance(zeta_id, label="highly_relevant", score=90)
            database.update_library_importance(alpha_id, importance=5)
            database.update_library_importance(zeta_id, importance=1)

            self.assertEqual(
                [paper["item"]["id"] for paper in database.list_latest_relevant_papers(sort_by="name")],
                [alpha_id, zeta_id],
            )
            self.assertEqual(database.list_latest_relevant_papers(sort_by="publish_date")[0]["item"]["id"], zeta_id)
            self.assertEqual(database.list_latest_relevant_papers(sort_by="relevance")[0]["item"]["id"], zeta_id)
            self.assertEqual(database.list_latest_relevant_papers(sort_by="importance")[0]["item"]["id"], alpha_id)

    def test_remove_moves_paper_to_end_with_gray_recoverable_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/remove-me",
                    "title": "Recoverable Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            active_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/still-active",
                    "title": "Still Active Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )

            remove_paper(database, {"item_id": item_id})

            papers = database.list_latest_relevant_papers()
            self.assertEqual([paper["item"]["id"] for paper in papers], [active_id, item_id])
            self.assertEqual(papers[-1]["library_entry"]["status"], "removed")
            self.assertTrue(papers[-1]["recoverable"])
            html = render_latest_papers_page(database)
            self.assertIn('class="paper removed"', html)
            self.assertIn("text-decoration: line-through", html)
            self.assertIn("Recover before", html)
            self.assertLess(html.index("Still Active Paper"), html.index("Recoverable Paper"))

            recover_paper(database, {"item_id": item_id})

            self.assertEqual({paper["item"]["id"] for paper in database.list_latest_relevant_papers()}, {item_id, active_id})

    def test_remove_works_for_team_record_without_library_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/orphan-remove",
                    "title": "Orphan Library Entry Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            with database.connect() as connection:
                connection.execute("DELETE FROM project_library_entries WHERE item_id = ?", (item_id,))

            remove_paper(database, {"item_id": item_id})

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[-1]["item"]["id"], item_id)
            self.assertEqual(papers[-1]["library_entry"]["status"], "removed")
            self.assertTrue(papers[-1]["recoverable"])
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT status, record_json FROM project_library_entries WHERE item_id = ?",
                    (item_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "removed")
            self.assertIn("restore_until", row["record_json"])

    def test_legacy_removed_team_record_without_library_entry_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/legacy-removed",
                    "title": "Legacy Removed Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            database.update_item_relevance(item_id, label="low_relevance", score=1, now=now)
            bundle = database.get_bundle(item_id)
            record = dict(bundle["team_record"])
            record.update({"review_status": "removed", "updated_at": now.isoformat()})
            with database.connect() as connection:
                connection.execute("DELETE FROM project_library_entries WHERE item_id = ?", (item_id,))
                connection.execute(
                    """
                    UPDATE team_research_records
                    SET review_status = ?, updated_at = ?, record_json = ?
                    WHERE item_id = ?
                    """,
                    (
                        record["review_status"],
                        record["updated_at"],
                        json.dumps(record, ensure_ascii=True, sort_keys=True),
                        item_id,
                    ),
                )

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[-1]["item"]["id"], item_id)
            self.assertEqual(papers[-1]["library_entry"]["status"], "removed")
            self.assertTrue(papers[-1]["recoverable"])
            html = render_latest_papers_page(database)
            self.assertIn("Legacy Removed Paper", html)
            self.assertIn('class="paper removed"', html)

            recover_paper(database, {"item_id": item_id})
            recovered = database.get_bundle(item_id)
            self.assertEqual(recovered["team_record"]["review_status"], "accepted")
            self.assertEqual(recovered["library_entries"][0]["status"], "candidate")

    def test_recovery_expires_after_24_hours(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/expired-recovery",
                    "title": "Expired Recovery Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            database.remove_item(item_id, now=now)

            with self.assertRaisesRegex(ValueError, "expired"):
                database.restore_item(item_id, now=now + timedelta(hours=25))


if __name__ == "__main__":
    unittest.main()
