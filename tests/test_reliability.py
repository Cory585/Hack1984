"""Reliability scores: factor values, boundaries, rounding, clamping and the tie-breaking order."""
import copy
import unittest

from conflict_check.reliability import (coverage, label, newest_year, order_ties, rate_expert, round_half_up,
                                        score_tie, site, source_kind)

ORCID = {"status": "confirmed", "by": "orcid"}
NOW = 2026


def ev(url="https://journals.example.org/p", api="exa", matched_by="full name", title="Paper (2025)", quote="q",
       paper=None, published=None):
    """Evidence; by default an Exa research paper (a DOI + conflict-of-interest heading on the page)."""
    if paper is None:
        paper = api == "exa"
    return {"url": url, "api": api, "matched_by": matched_by, "title": title, "quote": quote, "verified": True,
            "paper_signals": paper, "published": published}


def tie(org="Veltrix Pharmaceuticals", evidence=None, categories=("consulting",), op=None, related=True):
    return {"org": org, "categories": list(categories), "category": categories[0], "related_to_story": related,
            "evidence": evidence if evidence is not None else [ev()], "open_payments": op}


class TestBoundariesAndRounding(unittest.TestCase):
    def test_labels_at_boundaries_take_the_higher_band(self):
        self.assertEqual([label(s) for s in (100, 80, 79, 60, 59, 0)],
                         ["Strong", "Strong", "Moderate", "Moderate", "Weak", "Weak"])
        self.assertIsNone(label(None))

    def test_round_half_up_including_float_noise(self):
        self.assertEqual(round_half_up(79.5), 80)
        self.assertEqual(round_half_up(79.49999999999), 80)   # float noise for 79.5
        self.assertEqual(round_half_up(79.49), 79)
        self.assertEqual(round_half_up(59.5), 60)
        self.assertEqual(round_half_up(0.5), 1)               # Python's round() would give 0

    def test_best_case_clamped_to_100_with_bonus(self):
        t = tie(evidence=[ev(), ev(url="https://a.example.edu/x", api="tavily"), ev(url="https://b.example.com/y", api="tavily")],
                categories=("employment",), op={"status": "name_match"})
        r = score_tie(t, ORCID, NOW)
        self.assertEqual(r["bonus"], 8)
        self.assertEqual(r["score"], 100)
        self.assertEqual(r["label"], "Strong")

    def test_worst_case_stays_above_zero_and_weak(self):
        t = tie(org="GSK", evidence=[ev(url="https://blog.example.com/x", api="tavily", matched_by="pronoun",
                                        title="old post 1998")], categories=("other",))
        r = score_tie(t, None, NOW)
        self.assertGreater(r["score"], 0)
        self.assertEqual(r["label"], "Weak")

    def test_no_evidence_is_zero_with_the_normal_shape(self):  # review 10.5
        r = score_tie(tie(evidence=[]), ORCID, NOW)
        self.assertEqual((r["score"], r["label"]), (0, "Weak"))
        full = score_tie(tie(), ORCID, NOW)
        self.assertEqual(set(r) - {"note"}, set(full))

    def test_score_uses_unrounded_factor_values(self):  # review 10.5
        from conflict_check.reliability import _weighted_score
        # 0.12496 -> 12.496 -> 12. Rounding the factor to 3 places first (0.125) would give 12.5 -> 13.
        factors = [{"key": "x", "value": .12496, "weight": 1, "note": ""}]
        self.assertEqual(_weighted_score(factors), 12)
        self.assertEqual(factors[0]["value"], .125)  # the display copy is rounded only afterwards


class TestFactors(unittest.TestCase):
    def f(self, t, identity=ORCID):
        return {x["key"]: x["value"] for x in score_tie(t, identity, NOW)["factors"]}

    def test_identity(self):
        self.assertEqual(self.f(tie())["identity"], 1.0)
        self.assertEqual(self.f(tie(), {"status": "confirmed", "by": "user"})["identity"], .8)
        self.assertEqual(self.f(tie(), None)["identity"], .5)

    def test_best_attribution_wins(self):
        t = tie(evidence=[ev(matched_by="pronoun"), ev(url="https://x.example.edu/a", api="tavily", matched_by="initials")])
        self.assertEqual(self.f(t)["attribution"], .75)

    def test_source_kinds(self):
        self.assertEqual(source_kind(ev()), "paper")
        self.assertEqual(source_kind(ev(url="https://med.example.edu/p", api="tavily")), "institution")
        self.assertEqual(source_kind(ev(url="https://www.example.ac.uk/p", api="tavily")), "institution")
        self.assertEqual(source_kind(ev(url="https://example.org/p", api="tavily")), "web")

    def test_exa_alone_doesnt_make_a_paper(self):  # review 10.2
        self.assertEqual(source_kind(ev(url="https://someblog.example.com/post", api="exa", paper=False)), "web")
        self.assertEqual(source_kind(ev(url="https://med.example.edu/news", api="exa", paper=False)), "institution")
        self.assertEqual(source_kind(ev(url="https://jamanetwork.com/journals/x", api="tavily", paper=False)), "paper")
        self.assertEqual(source_kind(ev(url="https://pmc.ncbi.nlm.nih.gov/articles/PMC1", api="tavily", paper=False)), "paper")

    def test_publication_date_beats_years_in_text(self):  # review 10.3
        from conflict_check.reliability import source_year
        self.assertEqual(source_year([ev(title="Annual report 2025", published="2019-03-01")], NOW), (2019, "published"))
        self.assertEqual(source_year([ev(title="Untitled", quote="consultant since 2012; founded in 2025")], NOW), (None, None))
        self.assertEqual(source_year([ev(title="Review (2024)")], NOW), (2024, "dated"))
        self.assertEqual(source_year([ev(title="x", published="2031-01-01")], NOW), (None, None))  # future date ignored
        note = next(f["note"] for f in score_tie(tie(evidence=[ev(published="2025-06-12T00:00:00Z")]), ORCID, NOW)["factors"]
                    if f["key"] == "recency")
        self.assertEqual(note, "published 2025")

    def test_same_website_counts_once(self):
        self.assertEqual(site("https://news.example.co.uk/a"), "example.co.uk")
        self.assertEqual(site("https://www.example.co.uk/b"), "example.co.uk")
        t = tie(evidence=[ev(url="https://news.example.co.uk/a", api="tavily"), ev(url="https://example.co.uk/b", api="tavily")])
        self.assertEqual(self.f(t)["corroboration"], .55)
        self.assertEqual(score_tie(t, ORCID, NOW)["sites"], 1)

    def test_corroboration_steps(self):
        evs = [ev(url=f"https://site{i}.example{i}.com/x", api="tavily") for i in range(3)]
        self.assertEqual(self.f(tie(evidence=evs[:2]))["corroboration"], .85)
        self.assertEqual(self.f(tie(evidence=evs))["corroboration"], 1.0)

    def test_most_specific_wording(self):
        self.assertEqual(self.f(tie(categories=("personal fees", "equity")))["wording"], 1.0)
        self.assertEqual(self.f(tie(categories=("personal fees",)))["wording"], .75)

    def test_recency_boundaries(self):
        def rec(year):
            return self.f(tie(evidence=[ev(title=f"Paper {year}")]))["recency"]
        self.assertEqual(rec(2023), 1.0)   # 3 years: still inside a 36-month disclosure window
        self.assertEqual(rec(2022), .75)
        self.assertEqual(rec(2020), .75)   # 6 years
        self.assertEqual(rec(2019), .5)
        self.assertEqual(self.f(tie(evidence=[ev(title="Undated")]))["recency"], .7)

    def test_year_detection_ignores_numbers_and_future(self):
        evs = [ev(title="9,400 adults; p = 0.2012; 2,025,000 dollars; due 2031", quote="")]
        self.assertIsNone(newest_year(evs, NOW))
        self.assertEqual(newest_year([ev(title="", quote="", url="https://x.org/2024/05/a")], NOW), 2024)
        self.assertEqual(newest_year([ev(title="doi:10.1001/jama.2023.1", quote="")], NOW), 2023)

    def test_acronym_org(self):
        self.assertEqual(self.f(tie(org="GSK"))["organization"], .8)
        self.assertEqual(self.f(tie(org="Eli Lilly"))["organization"], 1.0)

    def test_ambiguous_open_payments_gives_no_bonus(self):
        self.assertEqual(score_tie(tie(op={"status": "ambiguous"}), ORCID, NOW)["bonus"], 0)
        self.assertEqual(score_tie(tie(op={"status": "error"}), ORCID, NOW)["bonus"], 0)


def rated(org, score, sites=1, best="paper", cats=("consulting",), related=True):
    return {"org": org, "related_to_story": related, "categories": list(cats),
            "reliability": {"score": score, "sites": sites, "best_source": best}}


class TestTieBreaking(unittest.TestCase):
    def order(self, ties):
        return [t["org"] for t in order_ties(ties)]

    def test_story_related_first_even_if_lower_score(self):
        self.assertEqual(self.order([rated("Strong Co", 95, related=False), rated("Story Co", 61)]),
                         ["Story Co", "Strong Co"])

    def test_higher_score_first(self):
        self.assertEqual(self.order([rated("A", 70), rated("B", 90)]), ["B", "A"])

    def test_equal_score_more_websites_first(self):
        self.assertEqual(self.order([rated("A", 80, sites=1), rated("B", 80, sites=2)]), ["B", "A"])

    def test_then_better_source(self):
        self.assertEqual(self.order([rated("A", 80, best="web"), rated("B", 80, best="institution"),
                                     rated("C", 80, best="paper")]), ["C", "B", "A"])

    def test_then_more_serious_tie(self):
        self.assertEqual(self.order([rated("A", 80, cats=("speaking",)), rated("B", 80, cats=("employment",)),
                                     rated("C", 80, cats=("personal fees", "equity"))]), ["B", "C", "A"])

    def test_then_name_case_insensitive(self):
        self.assertEqual(self.order([rated("beta", 80), rated("Alpha", 80), rated("ALPHA2", 80)]),
                         ["Alpha", "ALPHA2", "beta"])

    def test_identical_keeps_found_order(self):
        a, b = rated("Same", 80), rated("Same", 80)
        a["id"], b["id"] = 1, 2
        self.assertEqual([t["id"] for t in order_ties([a, b])], [1, 2])
        self.assertEqual([t["id"] for t in order_ties([b, a])], [2, 1])

    def test_missing_reliability_sorts_last_without_crashing(self):
        self.assertEqual(self.order([{"org": "Unscored", "related_to_story": True}, rated("Scored", 10)]),
                         ["Scored", "Unscored"])


class TestCoverageAndDeterminism(unittest.TestCase):
    def test_coverage_not_rated_without_identity_or_on_error(self):
        self.assertIsNone(coverage({"identity": {"status": "not_confirmed"}}, []))
        self.assertIsNone(coverage({"identity": ORCID, "status": "error"}, []))

    def test_coverage_levels(self):
        none = coverage({"identity": ORCID, "status": "no_confirmed_connections"}, [])
        self.assertEqual(none["label"], "Weak")  # nothing was actually checked
        pages = [{"api": "exa"}] * 3 + [{"api": "tavily"}] * 3
        full = coverage({"identity": ORCID, "status": "no_confirmed_connections"}, pages)
        self.assertEqual((full["score"], full["label"]), (100, "Strong"))
        one = coverage({"identity": ORCID, "status": "no_confirmed_connections"}, [{"api": "exa"}])
        self.assertEqual(one["label"], "Moderate")

    def test_coverage_counts_only_pages_about_the_person(self):  # review 10.4
        unrelated = [{"api": "exa", "about": False}] * 3 + [{"api": "tavily", "about": False}] * 3
        c = coverage({"identity": ORCID, "status": "no_confirmed_connections"}, unrelated)
        self.assertEqual(c["label"], "Weak")
        self.assertIn("0 of 6 pages", next(f["note"] for f in c["factors"] if f["key"] == "pages"))

    def test_rating_twice_gives_the_same_result(self):
        result = {"identity": ORCID, "status": "connections_found",
                  "ties": [tie("Halden Biotech", related=False), tie("Corvane", categories=("equity",)), tie("Veltrix")],
                  "disclosed": []}
        first = rate_expert(copy.deepcopy(result), [{"api": "exa"}], NOW)
        second = rate_expert(copy.deepcopy(first), [{"api": "exa"}], NOW)
        self.assertEqual([t["org"] for t in first["ties"]], [t["org"] for t in second["ties"]])
        self.assertEqual([t["reliability"]["score"] for t in first["ties"]],
                         [t["reliability"]["score"] for t in second["ties"]])
        self.assertEqual([t["org"] for t in first["ties"]], ["Corvane", "Veltrix", "Halden Biotech"])


if __name__ == "__main__":
    unittest.main()


class TestSameNameCap(unittest.TestCase):
    def rate(self, seen):
        t = tie(evidence=[{"url": "https://x.edu/a", "matched_by": "full name", "paper_signals": True,
                           "published": "2025-01-01", "affiliation_seen": seen}])
        return score_tie(t, ORCID, NOW)

    def test_capped_weak_when_no_source_mentions_their_institution(self):
        r = self.rate(False)
        self.assertEqual((r["score"], r["label"], r["capped"]), (59, "Weak", True))
        self.assertIn("different person", r["cap_note"])

    def test_not_capped_when_seen_or_unknown(self):
        for seen in (True, None):
            r = self.rate(seen)
            self.assertNotIn("capped", r)
            self.assertGreater(r["score"], 59)
