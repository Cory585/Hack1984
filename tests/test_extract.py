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
