#!/usr/bin/env python3

from __future__ import annotations

import unittest

from tools.portfolio_demo import check_artifacts, summary_text
from tools import test_render_portfolio as render_fixture


class PortfolioDemoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = render_fixture.PortfolioRendererTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.result = self.fixture.result

    def test_summary_contains_each_evidence_category(self) -> None:
        output = summary_text(self.result)
        self.assertIn("tooling aaaaaaaaaaaa | RTL bbbbbbbbbbbb", output)
        self.assertIn("architecture signatures 38/38", output)
        self.assertIn("BENCHMARKS", output)
        self.assertIn("ROUTED ARTIX-7 RESULTS", output)

    def test_artifact_check_rejects_stale_transcript_and_invalid_gif(self) -> None:
        (self.root / "docs/portfolio-demo.txt").write_text("stale\n", encoding="utf-8")
        (self.root / "docs/portfolio-demo.tape").write_text(
            "Output docs/portfolio-demo.gif\nType \"python3 tools/portfolio_demo.py --paced\"\n",
            encoding="utf-8",
        )
        (self.root / "docs/portfolio-demo.gif").write_bytes(b"not a gif")
        errors = check_artifacts(self.root, self.result)
        self.assertIn("portfolio demo transcript is stale", errors)
        self.assertIn("portfolio demo GIF is invalid", errors)

    def test_artifact_check_accepts_matching_files(self) -> None:
        (self.root / "docs/portfolio-demo.txt").write_text(summary_text(self.result), encoding="utf-8")
        (self.root / "docs/portfolio-demo.tape").write_text(
            "Output docs/portfolio-demo.gif\nType \"python3 tools/portfolio_demo.py --paced\"\n",
            encoding="utf-8",
        )
        (self.root / "docs/portfolio-demo.gif").write_bytes(b"GIF89a" + b"0" * 2048)
        self.assertEqual(check_artifacts(self.root, self.result), [])


if __name__ == "__main__":
    unittest.main()
