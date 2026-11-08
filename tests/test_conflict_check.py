"""Offline tests. All names and companies in the fixtures are fictional."""
import os
import shutil
import tempfile
import unittest

from conflict_check.extract import extract_experts
from conflict_check.pipeline import gather_pages, check_article
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


def op_row(npi, payer="VELTRIX PHARMACEUTICALS INC.", amount="1500.00", nature="Consulting Fee"):
    return {"covered_recipient_npi": npi, "recipient_city": "LAKESIDE", "recipient_state": "MN",
            "covered_recipient_specialty_1": "Allopathic & Osteopathic Physicians|Cardiovascular Disease",
            "applicable_manufacturer_or_applicable_gpo_making_payment_name": payer,
            "total_amount_of_payment_usdollars": amount, "nature_of_payment_or_transfer_of_value": nature}


def fake_fetcher(orcid_hits, op_npis=("1234567890",)):
    def fetch(method, url, headers, body):
        if "openpaymentsdata.cms.gov" in url:
            payer = body["conditions"][2]["value"]
            return {"results": [op_row(n) for n in op_npis] if "VELTRIX" in payer else []}
        if "orcid.org" in url and url.endswith("/personal-details"):
            return {"name": {"given-names": {"value": "Maren"}, "family-name": {"value": "Okafor"}}}
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
        veltrix = okafor["ties"][0]
        self.assertEqual(veltrix["org"], "Veltrix Pharmaceuticals")  # story-related first
        badge = veltrix["open_payments"]
        self.assertEqual(badge["status"], "name_match")
        self.assertEqual(badge["payments"], 2)            # one row per dataset year
        self.assertEqual(badge["total_usd"], 3000.0)
        self.assertIsNone(okafor["ties"][1]["open_payments"])  # Halden: no payments, no badge
        self.assertEqual(by["Tobias Wren"]["status"], "identity_not_confirmed")
        # Experts run in parallel and the fake search returns the same URL for everyone, so a repeated
        # extract may legitimately come from the cache; nothing may error or miss.
        self.assertTrue(all(c["source"] in ("live", "cache") for c in result["calls"]))
        self.assertIn("live", {c["source"] for c in result["calls"]})

        replayed = check_article(self.session(replay=True), text=ARTICLE)
        self.assertEqual(replayed["experts"], result["experts"])
        self.assertTrue(all(c["source"] == "cache" for c in replayed["calls"]))

    def test_ambiguous_identity_shows_no_ties(self):
        result = check_article(self.session(fetcher=fake_fetcher(2)), text=ARTICLE)
        okafor = next(e for e in result["experts"] if e["name"] == "Maren Okafor")
        self.assertEqual(okafor["status"], "identity_not_confirmed")
        self.assertEqual(okafor["ties"], [])

    def test_open_payments_withheld_when_several_physicians(self):
        result = check_article(self.session(fetcher=fake_fetcher(1, op_npis=("111", "222"))), text=ARTICLE)
        okafor = next(e for e in result["experts"] if e["name"] == "Maren Okafor")
        self.assertEqual(okafor["ties"][0]["open_payments"]["status"], "ambiguous")

    def test_user_pick_confirms_identity(self):
        experts = [{"name": "Maren Okafor", "affiliation": "Lakeside University", "orcid": "0000-0000-0000-0001"}]
        result = check_article(self.session(fetcher=fake_fetcher(2)), text=ARTICLE, experts=experts)
        okafor = result["experts"][0]
        self.assertEqual(okafor["identity"]["by"], "user")
        self.assertEqual(okafor["status"], "connections_found")

    def test_user_pick_rejects_wrong_surname(self):
        experts = [{"name": "Tobias Wren", "orcid": "0000-0000-0000-0001"}]  # record is Maren Okafor
        result = check_article(self.session(fetcher=fake_fetcher(1)), text=ARTICLE, experts=experts)
        self.assertEqual(result["experts"][0]["status"], "identity_not_confirmed")

    def test_reviewed_list_drops_single_names_and_streams_events(self):
        events, calls = [], []
        s = self.session(fetcher=fake_fetcher(1), on_call=calls.append)
        check_article(s, text=ARTICLE, experts=[{"name": "Okafor"}, {"name": "Maren Okafor",
                      "affiliation": "Lakeside University"}], on_event=events.append)
        # ties arrive first (badges pending), then an update as the Veltrix badge lands, then the final one
        self.assertEqual([e["type"] for e in events], ["start", "expert", "update", "update"])
        self.assertEqual(events[0]["experts"], ["Maren Okafor"])
        self.assertEqual(calls, s.calls)

    def test_early_result_has_ties_without_badges_then_update_adds_them(self):
        events = []
        s = self.session(fetcher=fake_fetcher(1))
        result = check_article(s, text=ARTICLE, experts=[{"name": "Maren Okafor", "affiliation": "Lakeside University"}],
                               on_event=events.append)
        early, arrived, final = events[1]["expert"], events[2]["expert"], events[3]["expert"]
        self.assertTrue(arrived["badges_pending"])  # streamed as soon as one badge is in
        self.assertEqual(arrived["ties"][0]["open_payments"]["status"], "name_match")
        self.assertTrue(early["badges_pending"])
        self.assertTrue(early["ties"])
        self.assertTrue(all(t["open_payments"] is None for t in early["ties"]))
        self.assertNotIn("badges_pending", final)
        self.assertEqual(final, result["experts"][0])
        self.assertEqual([t["org"] for t in early["ties"]] and sorted(t["org"] for t in early["ties"]),
                         sorted(t["org"] for t in final["ties"]))

    def test_tavily_raw_content_skips_the_extract_call(self):
        def fetch(method, url, headers, body):
            if "api.exa.ai" in url:
                return {"results": []}
            if url.endswith("/search"):
                assert body["include_raw_content"] is True
                return {"results": [{"url": "https://example.org/a", "title": "A", "raw_content": PAPER},
                                    {"url": "https://example.org/b", "title": "B"}]}  # no text: needs an extract
            if url.endswith("/extract"):
                assert body["urls"] == ["https://example.org/b"]
                return {"results": [{"url": u, "raw_content": UNRELATED} for u in body["urls"]]}
            raise AssertionError(url)
        pages = gather_pages(self.session(fetcher=fetch), "Maren Okafor", "Lakeside University")
        self.assertEqual({p["url"]: p["text"] for p in pages},
                         {"https://example.org/a": PAPER, "https://example.org/b": UNRELATED})

    def test_no_early_event_when_open_payments_is_off(self):
        import os
        events = []
        os.environ["OPEN_PAYMENTS"] = "off"
        try:
            check_article(self.session(fetcher=fake_fetcher(1)), text=ARTICLE,
                          experts=[{"name": "Maren Okafor", "affiliation": "Lakeside University"}],
                          on_event=events.append)
        finally:
            del os.environ["OPEN_PAYMENTS"]
        self.assertEqual([e["type"] for e in events], ["start", "expert"])

    def test_replay_miss(self):
        with self.assertRaises(ReplayMiss):
            self.session(replay=True).request("exa", "x", "GET", "https://api.exa.ai/none")


if __name__ == "__main__":
    unittest.main()


class InputValidationTests(unittest.TestCase):
    def test_bad_experts_and_urls_are_value_errors(self):
        s = Session(cache_dir="unused", replay=True)
        for bad in ("Eric Topol", [1, None], {"name": "x"}):
            with self.assertRaises(ValueError):
                check_article(s, text="hi", experts=bad)
        for url in ("not a url", "ftp://x.org/a", "http://", "javascript:alert(1)"):
            with self.assertRaises(ValueError):
                check_article(s, url=url)

    def test_odd_field_types_do_not_crash(self):
        s = Session(cache_dir="unused", replay=True)
        r = check_article(s, text="hi", experts=[{"name": 5, "affiliation": 7, "orcid": 1}])
        self.assertEqual(r["experts"], [])

    def test_duplicate_experts_are_checked_once(self):
        from conflict_check.pipeline import experts_from_request
        dup = {"name": "Maria Okafor", "affiliation": "Lakeside"}
        got = experts_from_request([dup, dict(dup, name="maria  okafor"), {"name": "Tobias Wren"}])
        self.assertEqual([e.name for e, _ in got], ["Maria Okafor", "Tobias Wren"])


class TestRetries(unittest.TestCase):
    def run_fetch(self, outcomes):
        import io, urllib.error, urllib.request
        from unittest import mock
        from conflict_check.session import urllib_fetcher
        calls, waits = [], []

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def fake_urlopen(req, timeout=0):
            calls.append(1)
            o = outcomes[len(calls) - 1]
            if isinstance(o, Exception):
                raise o
            return Resp(o)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            try:
                return urllib_fetcher("GET", "http://x", {}, None, sleep=waits.append), len(calls), waits
            except RuntimeError as e:
                return e, len(calls), waits

    def http(self, code, retry_after=None):
        import email.message, io, urllib.error
        h = email.message.Message()
        if retry_after:
            h["Retry-After"] = retry_after
        return urllib.error.HTTPError("http://x", code, "err", h, io.BytesIO(b"{}"))

    def test_retries_429_then_succeeds(self):
        data, n, waits = self.run_fetch([self.http(429, "1"), b'{"ok": 1}'])
        self.assertEqual((data, n), ({"ok": 1}, 2))
        self.assertTrue(1 <= waits[0] <= 1.25)  # honours Retry-After

    def test_retries_dropped_connection(self):
        import urllib.error
        data, n, _ = self.run_fetch([urllib.error.URLError("reset"), TimeoutError(), b'{"ok": 2}'])
        self.assertEqual((data, n), ({"ok": 2}, 3))

    def test_gives_up_after_retries_and_does_not_retry_4xx(self):
        err, n, _ = self.run_fetch([self.http(503)] * 3)
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(n, 3)
        err, n, _ = self.run_fetch([self.http(401), b"{}"])
        self.assertIn("HTTP 401", str(err))
        self.assertEqual(n, 1)
