"""Expert extraction on common news attribution styles (fictional names)."""
import unittest

from conflict_check.extract import extract_experts

CASES = [
    # (text, expected [(name, affiliation, kind)])
    ("“It works,” said Maren Okafor, MD, a cardiologist at Lakeside University.",
     [("Maren Okafor", "Lakeside University", "expert")]),
    ("Tobias Wren, PhD, of the Northfield Institute, said the effect was small.",
     [("Tobias Wren", "Northfield Institute", "expert")]),
    ("Maren Okafor, professor of medicine at Lakeside University School of Medicine, said it was promising.",
     [("Maren Okafor", "Lakeside University School of Medicine", "expert")]),
    ("“Promising,” said Maren Okafor, who directs the heart program at Lakeside University.",
     [("Maren Okafor", "Lakeside University", "expert")]),
    ("The drug is safe, according to Maren Okafor of Lakeside University.",
     [("Maren Okafor", "Lakeside University", "expert")]),
    ("“We need more data,” says Dr. Tobias Wren.", [("Tobias Wren", None, "expert")]),
    ("Lakeside University cardiologist Maren Okafor said the trial was well run.",
     [("Maren Okafor", "Lakeside University", "expert")]),
    ("Maren J. Okafor, a cardiologist at Lakeside University, said it worked.",
     [("Maren J. Okafor", "Lakeside University", "expert")]),
    ("Maren Okafor, who led the study at Lakeside University, said results were clear.",
     [("Maren Okafor", "Lakeside University", "expert")]),
    ("Study co-author Maren Okafor of Lakeside University said results were clear.",
     [("Maren Okafor", "Lakeside University", "expert")]),
    ("President Joe Biden said the drug was great. Veltrix Pharmaceuticals said in a statement it was pleased.",
     [("Joe Biden", None, "other")]),
    ("Anna Price, a spokesperson for Veltrix Pharmaceuticals, said the company was pleased.",
     [("Anna Price", "Veltrix Pharmaceuticals", "other")]),
    ("The study appeared in the Lakeside Medical Journal on Tuesday.", []),
    # Patterns seen in real health news (fictionalized):
    ("The nonprofit Patient Watch noted the change. Ana Ruiz, Research Director at Patient Watch wrote in a statement.",
     [("Ana Ruiz", "Patient Watch", "expert")]),
    ("The Alliance for Drug Makers's CEO Sam Bell wrote in a statement that his group is pleased.",
     [("Sam Bell", None, "other")]),
    ("“It's risky,” its executive director Omar Haddad wrote in a statement.", [("Omar Haddad", None, "other")]),
    ("Lena Ortiz, a bioethicist at the University of Lakeside, said it was troubling.",
     [("Lena Ortiz", "University of Lakeside", "expert")]),
    ("Dr. Ralph Venn studied the colony. “It was grim,” says Venn, who is based in Chile and is a wildlife "
     "veterinarian with the Northfield University, Davis campus.",
     [("Ralph Venn", "Northfield University", "expert")]),
    ("Mira Kollo, a caregiver at a UNICEF-supported nursery in Bunia, said the children were safe.", []),
]


class TestExtract(unittest.TestCase):
    def test_attribution_styles(self):
        for text, expected in CASES:
            with self.subTest(text=text):
                got = [(e.name, e.affiliation, e.kind) for e in extract_experts(text)]
                self.assertEqual(got, expected)

    def test_merges_mentions_and_ranks_experts_first(self):
        text = ("Anna Price, a spokesperson for Veltrix, said it was pleased. Price added more. Price said more. "
                "Maren Okafor, a cardiologist at Lakeside University, said it was promising.")
        experts = extract_experts(text)
        self.assertEqual([e.name for e in experts], ["Maren Okafor", "Anna Price"])
        self.assertEqual(experts[1].mentions, 3)

    def test_credentials_recorded(self):
        e = extract_experts("Maren Okafor, MD, MPH, a cardiologist at Lakeside University, said so.")[0]
        self.assertEqual(e.credentials, "MD, MPH")


if __name__ == "__main__":
    unittest.main()


class TestMarkdownPages(unittest.TestCase):
    NPR = ('"Maybe you need to treat longer," says [Roger Blumenthal](https://profiles.hopkinsmedicine.org/provider/roger-s-blumenthal/2708415), '
           'a cardiologist at Johns Hopkins University. "Very disappointing," says [Steven Nissen](https://providers.clevelandclinic.org/provider/steven-nissen/4268279), '
           'a cardiologist at the Cleveland Clinic who led the study. ![photo](https://x.org/a(1).jpg)')

    def test_names_inside_markdown_links_are_found(self):
        from conflict_check.extract import extract_experts
        got = {e.name: e.affiliation for e in extract_experts(self.NPR)}
        self.assertEqual(got.get("Roger Blumenthal"), "Johns Hopkins University")
        self.assertEqual(got.get("Steven Nissen"), "Cleveland Clinic")

    def test_strip_keeps_link_text_and_drops_images(self):
        from conflict_check.extract import strip_markdown_links
        self.assertEqual(strip_markdown_links("a [b c](https://x.org/q(1)) ![i](u) d"), "a b c  d")


class TestInstitutionBeforeRole(unittest.TestCase):
    def test_a_yale_university_cardiologist(self):
        from conflict_check.extract import extract_experts
        got = {e.name: e for e in extract_experts('"It was jarring," says Harlan Krumholz, a Yale University cardiologist. "Yes."')}
        self.assertEqual(got["Harlan Krumholz"].affiliation, "Yale University")
        self.assertEqual(got["Harlan Krumholz"].kind, "expert")
