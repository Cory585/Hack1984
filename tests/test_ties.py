"""Tie extraction on realistic disclosure wording. All names and companies are fictional,
except well-known funders/companies used only as organization names."""
import unittest

from conflict_check.ties import (category, classify_tie, distinctive_tokens, find_ties, same_org,
                                 segments, split_clauses, verify_quote)

NAME, AFF = "Maren Okafor", ["Lakeside University"]


def ties(text, name=NAME, exclude=AFF):
    return {t["org"]: t for t in find_ties([{"url": "u", "title": "t", "text": text, "api": "x"}], name, exclude)}


class TestAttribution(unittest.TestCase):
    def test_multi_person_sentence_only_counts_own_segment(self):
        t = ties("Okafor M, Lee J. Disclosures: Dr Lee reports grants from Corvane Biologics, and "
                 "Dr Okafor reports personal fees from Veltrix Pharmaceuticals outside the submitted work.")
        self.assertEqual(set(t), {"Veltrix Pharmaceuticals"})

    def test_initials_separated_by_semicolons(self):
        t = ties("Okafor M, Lee J. Competing interests: J.L. reports grants from Corvane Biologics; "
                 "M.O. reports consulting fees from Veltrix Pharmaceuticals.")
        self.assertEqual(set(t), {"Veltrix Pharmaceuticals"})

    def test_pronoun_continues_previous_sentence(self):
        t = ties("Maren Okafor, MD, is a cardiologist at Lakeside University. She serves on the scientific "
                 "advisory board of Halden Biotech and holds stock in Corvane Biologics.")
        self.assertEqual(set(t), {"Halden Biotech", "Corvane Biologics"})
        self.assertEqual(t["Corvane Biologics"]["category"], "equity")

    def test_pronoun_after_someone_else_is_not_attributed(self):
        self.assertEqual(ties("Maren Okafor wrote the paper. Tobias Wren is a reviewer. "
                              "He consults for Corvane Biologics."), {})

    def test_page_must_name_the_person(self):
        self.assertEqual(ties("Dr. Okafor reports consulting fees from Veltrix Pharmaceuticals."), {})


class TestNegation(unittest.TestCase):
    def test_declares_no_competing_interests(self):
        self.assertEqual(ties("Maren Okafor. Conflict of interest: M.O. declares no competing interests."), {})

    def test_no_conflicts_other_than_is_still_a_tie(self):
        t = ties("Maren Okafor has no conflicts of interest other than consulting fees from Veltrix Pharmaceuticals.")
        self.assertEqual(set(t), {"Veltrix Pharmaceuticals"})


class TestOrganizations(unittest.TestCase):
    def test_lists_and_all_generic_names(self):
        t = ties("Maren Okafor reports personal fees from Veltrix Pharmaceuticals, Halden Biotech, and "
                 "Bristol-Myers Squibb, and grants from the National Institutes of Health.")
        self.assertEqual(set(t), {"Veltrix Pharmaceuticals", "Halden Biotech", "Bristol-Myers Squibb",
                                  "National Institutes of Health"})
        self.assertEqual(t["National Institutes of Health"]["category"], "research funding")
        self.assertEqual(t["Halden Biotech"]["category"], "personal fees")

    def test_disclosure_phrases_are_not_organizations(self):
        t = ties("Maren Okafor. Personal Fees: Dr. Okafor received Advisory Board fees from Veltrix Pharmaceuticals Inc.")
        self.assertEqual(set(t), {"Veltrix Pharmaceuticals Inc"})

    def test_ampersand_and_company_suffix(self):
        t = ties("Maren Okafor has served as a consultant to Eli Lilly and Company and Johnson & Johnson.")
        self.assertEqual(set(t), {"Eli Lilly", "Johnson & Johnson"})

    def test_own_employer_excluded(self):
        t = ties("Maren Okafor is an employee of Lakeside University and consults for Veltrix Pharmaceuticals.")
        self.assertEqual(set(t), {"Veltrix Pharmaceuticals"})

    def test_same_org_across_pages_is_merged(self):
        pages = [{"url": f"https://example.org/{i}", "title": "t", "api": "x",
                  "text": f"Maren Okafor reports consulting fees from {org}."}
                 for i, org in enumerate(["Veltrix Pharmaceuticals", "Veltrix Pharmaceuticals Inc"])]
        found = find_ties(pages, NAME)
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["evidence"]), 2)


class TestHelpers(unittest.TestCase):
    def test_verify_quote(self):
        self.assertTrue(verify_quote("fees  from\nVeltrix", "consulting fees from Veltrix."))
        self.assertFalse(verify_quote("fees from Acme", "consulting fees from Veltrix."))
        self.assertFalse(verify_quote("", "anything"))

    def test_split_clauses_keeps_abbreviations(self):
        self.assertEqual(split_clauses("Dr. Okafor et al. reported results. Next."),
                         ["Dr. Okafor et al. reported results.", "Next."])

    def test_segments(self):
        self.assertEqual(segments("Dr Lee reports A, and Dr Okafor reports B"), ["Dr Lee reports A", "Dr Okafor reports B"])
        self.assertEqual(segments("M.O. reports A and serves on B"), ["M.O. reports A and serves on B"])

    def test_org_matching(self):
        self.assertTrue(same_org("Veltrix Pharmaceuticals", "VELTRIX PHARMACEUTICALS INC."))
        self.assertFalse(same_org("Veltrix", "Halden Biotech"))
        self.assertEqual(distinctive_tokens("Company"), [])
        self.assertEqual(category("speakers bureau"), "speaking")

    def test_classify(self):
        article = "Dr. Maren Okafor, who consults for Veltrix, praised the drug.\n\nHalden Biotech declined to comment."
        self.assertTrue(classify_tie({"org": "Veltrix"}, article, "Okafor")["disclosed_in_article"])
        halden = classify_tie({"org": "Halden Biotech"}, article, "Okafor")
        self.assertFalse(halden["disclosed_in_article"])
        self.assertTrue(halden["related_to_story"])


if __name__ == "__main__":
    unittest.main()
