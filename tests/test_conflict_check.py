"""Offline tests. All names and companies in the fixtures are fictional."""
import os
import shutil
import tempfile
import unittest

from conflict_check.extract import extract_experts
from conflict_check.pipeline import check_article
from conflict_check.session import ReplayMiss, Session
from conflict_check.ties import classify_tie, find_ties, split_clauses, verify_quote

HERE = os.path.dirname(__file__)
with open(os.path.join(HERE, "fixtures", "article.txt"), encoding="utf-8") as f:
    ARTICLE = f.read()

PAPER = (
    "Okafor M, Lee J. Long-term outcomes of PCSK9 therapy. Journal of Cardiac Care. 2025.\n"
    "Competing interests: M.O. reports consulting fees from Veltrix Pharmaceuticals and serves on an "
    "advisory board for Halden Biotech; J.L. reports grants from Lakeside University. "
    "Dr. Okafor is an employee of Lakeside University."
)
UNRELATED = "Maren Smith reports consulting fees from Orbis Labs."


class TestExtract(unittest.TestCase):
    def test_finds_experts_with_affiliation(self):
        experts = {e.name: e for e in extract_experts(ARTICLE)}
        self.assertIn("Maren Okafor", experts)
        self.assertIn("Tobias Wren", experts)
        self.assertEqual(experts["Maren Okafor"].affiliation, "Lakeside University")
        self.assertEqual(experts["Tobias Wren"].affiliation, "Northfield Institute of Public Health")
        self.assertNotIn("Veltrix Pharmaceuticals", experts)


class TestTies(unittest.TestCase):
    def pages(self):
        return [{"url": "https://example.org/paper", "title": "Paper", "text": PAPER, "api": "exa"},
                {"url": "https://example.org/other", "title": "Other", "text": UNRELATED, "api": "tavily"}]

    def test_ties_need_name_and_org_and_verified_quote(self):
        ties = {t["org"]: t for t in find_ties(self.pages(), "Maren Okafor", exclude_orgs=["Lakeside University"])}
        self.assertIn("Veltrix Pharmaceuticals", ties)
        self.assertIn("Halden Biotech", ties)
        self.assertNotIn("Lakeside University", ties)  # own employer, excluded
        self.assertNotIn("Orbis Labs", ties)            # different person
        for t in ties.values():
            for ev in t["evidence"]:
                self.assertTrue(verify_quote(ev["quote"], PAPER))

    def test_verify_quote_rejects_invented_text(self):
        self.assertFalse(verify_quote("M.O. is paid by Acme Corp", PAPER))

    def test_classify(self):
        tie = classify_tie({"org": "Veltrix Pharmaceuticals"}, ARTICLE, "Okafor")
        self.assertTrue(tie["related_to_story"])
        self.assertFalse(tie["disclosed_in_article"])
        tie = classify_tie({"org": "Halden Biotech"}, ARTICLE, "Okafor")
        self.assertFalse(tie["related_to_story"])

    def test_split_keeps_abbreviations(self):
        self.assertIn("Dr. Okafor is an employee of Lakeside University.", split_clauses(PAPER))


def fake_fetcher(orcid_hits):
    def fetch(method, url, headers, body):
        if "orcid.org" in url:
            if "Okafor" in url:
                return {"num-found": orcid_hits, "expanded-result": [
                    {"orcid-id": f"0000-0000-0000-000{i}", "given-names": "Maren", "family-names": "Okafor",
                     "institution-name": ["Lakeside University"]} for i in range(orcid_hits)] or None}
            return {"num-found": 0, "expanded-result": None}
        if "api.exa.ai" in url:
            return {"results": [{"url": "https://example.org/paper", "title": "Paper", "text": PAPER}]}
        if url.endswith("/search"):
            return {"results": [{"url": "https://example.org/other", "title": "Other"}]}
        if url.endswith("/extract"):
            return {"results": [{"url": u, "raw_content": UNRELATED} for u in body["urls"]]}
        raise AssertionError(url)
    return fetch


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.cache = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.cache, ignore_errors=True)

    def session(self, **kw):
        return Session(cache_dir=self.cache, tavily_key="t", exa_key="e", **kw)

    def test_end_to_end_then_replay(self):
        result = check_article(self.session(fetcher=fake_fetcher(1)), text=ARTICLE)
        by = {e["name"]: e for e in result["experts"]}
        okafor = by["Maren Okafor"]
        self.assertEqual(okafor["status"], "connections_found")
        self.assertEqual(okafor["ties"][0]["org"], "Veltrix Pharmaceuticals")  # story-related first
        self.assertEqual(by["Tobias Wren"]["status"], "identity_not_confirmed")
        self.assertTrue(all(c["source"] == "live" for c in result["calls"]))

        replayed = check_article(self.session(replay=True), text=ARTICLE)
        self.assertEqual(replayed["experts"], result["experts"])
        self.assertTrue(all(c["source"] == "cache" for c in replayed["calls"]))

    def test_ambiguous_identity_shows_no_ties(self):
        result = check_article(self.session(fetcher=fake_fetcher(2)), text=ARTICLE)
        okafor = next(e for e in result["experts"] if e["name"] == "Maren Okafor")
        self.assertEqual(okafor["status"], "identity_not_confirmed")
        self.assertEqual(okafor["ties"], [])

    def test_replay_miss(self):
        with self.assertRaises(ReplayMiss):
            self.session(replay=True).request("exa", "x", "GET", "https://api.exa.ai/none")


if __name__ == "__main__":
    unittest.main()
