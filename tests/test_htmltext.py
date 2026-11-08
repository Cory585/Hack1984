import unittest

from conflict_check.htmltext import html_to_text

PAGE = """<!doctype html><html><head><title>New pill | Example News</title>
<script>var x = "<p>not text</p>";</script><style>p{color:red}</style></head>
<body><nav><p>Home · Health · Science and other menu items here</p></nav>
<article><h1>New pill cuts heart attack risk in trial</h1>
<p>A once-daily pill lowered the risk of heart attack by 18 percent, researchers reported.</p>
<figure><p>Photo caption that should be dropped from the text.</p></figure>
<p>&ldquo;This is meaningful,&rdquo; said Maren Okafor, a cardiologist at Lakeside University.<br>She added more.</p>
<p>Share</p></article>
<footer><p>Copyright Example News, all rights reserved, 2026.</p></footer></body></html>"""


class TestHtmlText(unittest.TestCase):
    def test_article_text_only(self):
        title, text = html_to_text(PAGE)
        self.assertEqual(title, "New pill | Example News")
        self.assertIn("lowered the risk of heart attack", text)
        self.assertIn("“This is meaningful,” said Maren Okafor", text)  # entities decoded
        for junk in ("not text", "menu items", "Photo caption", "Copyright", "Share"):
            self.assertNotIn(junk, text)
        self.assertEqual(len(text.split("\n\n")), 3)

    def test_no_article_element_falls_back_to_all_paragraphs(self):
        _, text = html_to_text("<body><p>Maren Okafor, a cardiologist at Lakeside University, said it worked.</p></body>")
        self.assertIn("Maren Okafor", text)

    def test_malformed_html(self):
        _, text = html_to_text("<p>Unclosed paragraph about a long enough sentence here<div><p>Second one, also long enough to keep.")
        self.assertIn("Second one", text)

    def test_empty(self):
        self.assertEqual(html_to_text(""), ("", ""))


if __name__ == "__main__":
    unittest.main()
