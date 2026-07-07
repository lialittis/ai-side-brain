from __future__ import annotations

import unittest

from team.research_interests import score_team_interests


class TeamResearchInterestsTest(unittest.TestCase):
    def test_agentic_security_aliases_match_without_extra_ui_keywords(self) -> None:
        scored = score_team_interests(
            {
                "id": "item_agentic_alias",
                "title": "Securing AI Agents Against Prompt Injection",
                "abstract": "This work studies LLM security for autonomous cyber reasoning agents.",
            },
            card=None,
            tags=[],
            interests=[{"keyword": "agentic security", "weight": 80}],
        )

        self.assertEqual(scored["matched_terms"], ["agentic security"])
        self.assertGreaterEqual(scored["score"], 70)
        self.assertTrue(any("prompt injection" in reason for reason in scored["reasons"]))

    def test_negative_interest_context_dampens_otherwise_matching_score(self) -> None:
        clean = score_team_interests(
            {
                "id": "item_clean_ai_security",
                "title": "LLM Security for Agent Tool Use",
                "abstract": "This paper studies prompt injection defenses for agentic workflows.",
            },
            card=None,
            tags=[],
            interests=[{"keyword": "agentic security", "weight": 80}],
        )
        dampened = score_team_interests(
            {
                "id": "item_generic_ai_application",
                "title": "LLM Security for Generic AI Application Workflows",
                "abstract": "This paper is a recommendation system only case study.",
            },
            card=None,
            tags=[],
            interests=[{"keyword": "agentic security", "weight": 80}],
        )

        self.assertLess(dampened["score"], clean["score"])
        self.assertEqual(dampened["matched_terms"], ["agentic security"])
        self.assertIn("generic ai application", dampened["matched_negative_keywords"])
        self.assertIn("recommendation system only", dampened["matched_negative_keywords"])

    def test_custom_interest_terms_override_curated_profile(self) -> None:
        default_scored = score_team_interests(
            {
                "id": "item_kernel_security",
                "title": "Kernel Security Analysis",
                "abstract": "This paper studies operating system hardening.",
            },
            card=None,
            tags=[],
            interests=[
                {
                    "keyword": "system security",
                    "weight": 80,
                    "positive_keywords": ["custom trusted runtime"],
                    "negative_keywords": ["toy benchmark only"],
                }
            ],
        )
        custom_scored = score_team_interests(
            {
                "id": "item_custom_runtime",
                "title": "Custom Trusted Runtime",
                "abstract": "This paper studies a secure runtime for production systems.",
            },
            card=None,
            tags=[],
            interests=[
                {
                    "keyword": "system security",
                    "weight": 80,
                    "positive_keywords": ["custom trusted runtime"],
                    "negative_keywords": ["toy benchmark only"],
                }
            ],
        )
        dampened = score_team_interests(
            {
                "id": "item_custom_runtime_toy",
                "title": "Custom Trusted Runtime",
                "abstract": "This is a toy benchmark only.",
            },
            card=None,
            tags=[],
            interests=[
                {
                    "keyword": "system security",
                    "weight": 80,
                    "positive_keywords": ["custom trusted runtime"],
                    "negative_keywords": ["toy benchmark only"],
                }
            ],
        )

        self.assertEqual(default_scored["matched_terms"], [])
        self.assertEqual(custom_scored["matched_terms"], ["system security"])
        self.assertGreater(custom_scored["score"], 0)
        self.assertLess(dampened["score"], custom_scored["score"])
        self.assertIn("toy benchmark only", dampened["matched_negative_keywords"])


if __name__ == "__main__":
    unittest.main()
