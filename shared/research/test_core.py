from __future__ import annotations

from datetime import datetime, timezone
import unittest

from shared.research import (
    create_research_card,
    create_research_source,
    example_topic_profiles,
    normalize_research_item,
    screen_relevance,
    validate_relevance_screening,
    validate_research_card,
    validate_research_item,
    validate_research_source,
)


class SharedResearchCoreTest(unittest.TestCase):
    def test_manual_source_to_relevance_screening(self) -> None:
        now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
        source = create_research_source(
            "manual",
            "demo-paper",
            submitted_by="team-demo",
            now=now,
            metadata={
                "title": "Dynamic radiative cooling with tunable emissivity",
                "authors": ["Example Author"],
                "abstract": (
                    "This simulation study reports measured or simulated cooling performance "
                    "for a switchable radiative cooling material. It discusses adaptive "
                    "emissivity or solar reflectance and connects material behavior to building "
                    "or energy outcomes."
                ),
                "year": 2026,
                "venue": "Example venue",
                "item_type": "paper",
            },
        )
        item = normalize_research_item(source, now=now)
        card = create_research_card(item, now=now)
        topic_profile = example_topic_profiles()[0]
        screening = screen_relevance(item, card, topic_profile, now=now)

        validate_research_source(source)
        validate_research_item(item)
        validate_research_card(card)
        validate_relevance_screening(screening)

        self.assertEqual(item["source_ids"], [source["id"]])
        self.assertEqual(card["item_id"], item["id"])
        self.assertEqual(screening["item_id"], item["id"])
        self.assertEqual(screening["topic_profile_id"], "dynamic-radiative-cooling")
        self.assertEqual(screening["label"], "highly_relevant")
        self.assertGreaterEqual(screening["score"], 60)
        self.assertIn("dynamic radiative cooling", screening["matched_terms"])

    def test_rejects_empty_source_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_value cannot be empty"):
            create_research_source("manual", "   ")


if __name__ == "__main__":
    unittest.main()
