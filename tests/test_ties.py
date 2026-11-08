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


class TestRealWorldDisclosures(unittest.TestCase):
    """Formats seen in real open-access papers (Europe PMC), with fictional names."""
    AUTHORS = ("Maren Okafor, Jose F. K. Lindqvist, Wanda S. Silva Júnior, Ruy Lyra da Costa Filho, "
               "Paula A. C. Moreno, Tomas Berg.\n")

    def ties_for(self, name, text):
        return set(ties(self.AUTHORS + text, name=name, exclude=[]))

    def test_run_together_sentences_with_multi_letter_initials(self):
        coi = ("Competing interests. MO has received speaker fees from Corvane Biologics and GSK.JFKL has received "
               "fees from Halden Biotech, Veltrix Pharmaceuticals, and MSD.TB has received grants from Orbis Labs.")
        self.assertEqual(self.ties_for("Maren Okafor", coi), {"Corvane Biologics", "GSK"})
        self.assertEqual(self.ties_for("Jose F. K. Lindqvist", coi), {"Halden Biotech", "Veltrix Pharmaceuticals", "MSD"})
        self.assertEqual(self.ties_for("Tomas Berg", coi), {"Orbis Labs"})

    def test_particles_and_suffixes_in_initials(self):
        coi = "WSSJ has received consulting fees from Corvane Biologics. RLCF reports grants from Halden Biotech."
        self.assertEqual(self.ties_for("Wanda S. Silva Júnior", coi), {"Corvane Biologics"})
        self.assertEqual(self.ties_for("Ruy Lyra da Costa Filho", coi), {"Halden Biotech"})

    def test_semicolon_continues_the_same_person(self):
        coi = ("Dr. Berg has received grants from Corvane Biologics; personal fees from Halden Biotech and Orbis Labs; "
               "and grants from Veltrix Pharmaceuticals, outside of the submitted work.")
        self.assertEqual(self.ties_for("Tomas Berg", coi),
                         {"Corvane Biologics", "Halden Biotech", "Orbis Labs", "Veltrix Pharmaceuticals"})

    def test_semicolon_with_a_new_subject_does_not_continue(self):
        coi = "Dr. Berg has received grants from Corvane Biologics; Dr. Okafor reports fees from Halden Biotech."
        self.assertEqual(self.ties_for("Tomas Berg", coi), {"Corvane Biologics"})
        self.assertEqual(self.ties_for("Maren Okafor", coi), {"Halden Biotech"})

    def test_stray_period_after_name(self):
        coi = "Dr. Berg. has received personal fees from Corvane Biologics."
        self.assertEqual(self.ties_for("Tomas Berg", coi), {"Corvane Biologics"})

    def test_several_people_with_nothing_to_disclose(self):
        coi = "Dr. Okafor, Dr. Moreno, and Dr. Berg have nothing to disclose."
        for name in ("Maren Okafor", "Paula A. C. Moreno", "Tomas Berg"):
            self.assertEqual(self.ties_for(name, coi), set())

    def test_spellings_of_one_company_are_merged(self):
        coi = ("MO has received fees from AstraZeneca, Astra Zeneca, Astra-Zeneca, Lilly, Eli Lilly, Eli-Lilly, "
               "Novo Nordisk and NovoNordisk.")
        found = {t["org"]: t for t in find_ties([{"url": "u", "title": "t", "api": "x", "text": self.AUTHORS + coi}],
                                                "Maren Okafor")}
        self.assertEqual(len(found), 3)
        self.assertIn("Eli Lilly", found)
        self.assertEqual(set(found["Eli Lilly"]["aliases"]), {"Lilly", "Eli-Lilly"})

    def test_country_suffix_kept_in_name(self):
        coi = "MO has received fees from Eli Lilly do Brasil and Takeda."
        self.assertEqual(self.ties_for("Maren Okafor", coi), {"Eli Lilly do Brasil", "Takeda"})


class TestReviewFindings(unittest.TestCase):
    """Cases from the PR review (RayanR000), reproduced before fixing."""

    def test_particle_as_given_name_keeps_its_initial(self):
        from conflict_check.ties import name_parts, person_patterns
        self.assertEqual(name_parts("Le Wang")[2], ["Le", "Wang"])
        clause = person_patterns("Le Wang")[1]
        self.assertTrue(clause.search("LW reports fees from Corvane Biologics."))
        self.assertFalse(clause.search("W reports fees from Corvane Biologics."))
        self.assertEqual(name_parts("Ruy Lyra da Silva Filho")[1:], ("Silva", ["Ruy", "Lyra", "Silva", "Filho"]))

    def test_page_check_needs_name_like_middle_words(self):
        from conflict_check.ties import person_patterns
        strong = person_patterns("Maren Okafor")[0]
        self.assertFalse(strong.search("Maren thanked Dr. Okafor"))
        self.assertFalse(strong.search("Maren\nOkafor"))
        self.assertTrue(strong.search("Maren J. Okafor"))
        self.assertTrue(strong.search("Maren de Okafor"))

    def test_no_space_after_title_still_verifies(self):
        page = "Maren Okafor. Disclosures: Dr.Okafor reports consulting fees from Veltrix Pharmaceuticals."
        self.assertEqual(set(ties(page)), {"Veltrix Pharmaceuticals"})

    def test_quote_excludes_other_peoples_disclosures(self):
        page = "Maren Okafor, Jon Fisk. MO reports fees from Halden Biotech; JF reports fees from Orbis Labs."
        quote = ties(page)["Halden Biotech"]["evidence"][0]["quote"]
        self.assertNotIn("Orbis", quote)
        self.assertNotIn("JF", quote)

    def test_quote_keeps_the_name_for_continuations(self):
        page = ("Tomas Berg. Dr. Berg has received grants from Corvane Biologics; personal fees from Halden Biotech; "
                "JF reports fees from Orbis Labs.")
        quote = ties(page, name="Tomas Berg")["Halden Biotech"]["evidence"][0]["quote"]
        self.assertIn("Dr. Berg", quote)
        self.assertIn("Halden Biotech", quote)
        self.assertNotIn("Orbis", quote)

    def test_company_merging_is_whole_word(self):
        from conflict_check.ties import same_company
        for a, b in [("Astra Zeneca", "AstraZeneca"), ("Astra-Zeneca", "AstraZeneca"), ("Pfizer", "Pfizer Inc"),
                     ("Lilly", "Eli Lilly"), ("Boehringer", "Boehringer Ingelheim"), ("NovoNordisk", "Novo Nordisk"),
                     ("Merck", "Merck Sharp & Dohme")]:
            self.assertTrue(same_company(a, b), (a, b))
        for a, b in [("Merck", "Merck KGaA"), ("Merck", "Merck Serono"), ("Amgen", "Amgenta"), ("GSK", "GSK Vaccines"),
                     ("Bayer", "Novartis")]:
            self.assertFalse(same_company(a, b), (a, b))
        self.assertEqual(same_company("Merck KGaA", "Merck"), same_company("Merck", "Merck KGaA"))  # symmetric

    def test_initial_plus_surname_subjects_still_split_people(self):
        page = ("Maren Okafor, Jon Lee. J. Lee reports fees from Acme Labs, and M. Okafor reports fees from Cora Labs. "
                "M. Okafor received grants from Bolt Labs.")
        self.assertEqual(set(ties(page, exclude=[])), {"Cora Labs", "Bolt Labs"})
        self.assertEqual(set(ties(page, name="Jon Lee", exclude=[])), {"Acme Labs"})

    def test_disclosed_check_uses_surname_not_suffix(self):
        from conflict_check.ties import surname
        article = "John Smith Jr said it worked.\n\nSmith, who consults for Veltrix, praised the drug."
        self.assertEqual(surname("John Smith Jr"), "Smith")
        self.assertTrue(classify_tie({"org": "Veltrix"}, article, surname("John Smith Jr"))["disclosed_in_article"])


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
