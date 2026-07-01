from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from personal.literature_radar import read_personal_radar_index, run_personal_literature_radar
from scripts import personal_literature_radar
from shared.literature_radar import create_radar_paper


class PersonalLiteratureRadarTest(unittest.TestCase):
    def test_run_personal_literature_radar_writes_report_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00006",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00006"},
                links={"arxiv": "https://arxiv.org/abs/2601.00006"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]) as arxiv:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            self.assertTrue(result["report_path"])
            report_path = Path(result["report_path"])
            self.assertTrue(report_path.exists())
            self.assertIn("Memory Safety for Agentic Security", report_path.read_text(encoding="utf-8"))
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["id"], result["run_id"])
            self.assertEqual(runs[0]["recommendations"][0]["title"], "Memory Safety for Agentic Security")
            self.assertEqual(arxiv.call_args.kwargs["query_terms"], ["memory safety"])

    def test_personal_literature_radar_cli_reads_history_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00007",
                title="Agentic Security for Memory Safety",
                abstract="Agentic security, LLM security, and memory safety.",
                identifiers={"arxiv_id": "2601.00007"},
                links={"arxiv": "https://arxiv.org/abs/2601.00007"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(["history", "--root-path", str(root), "--json"])

            self.assertEqual(code, 0)
            history = json.loads(stdout.getvalue())
            self.assertEqual(history[0]["recommendation_count"], 1)
            self.assertEqual(history[0]["recommendations"][0]["title"], "Agentic Security for Memory Safety")


if __name__ == "__main__":
    unittest.main()
