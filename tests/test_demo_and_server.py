"""The built-in demo (fictional data) and the HTTP server, end to end."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from conflict_check import demo
from conflict_check.pipeline import check_article, find_experts
from conflict_check.server import Handler


def fast():
    return demo.demo_session(delay=(0, 0))


class TestDemo(unittest.TestCase):
    def test_find_experts_sets_the_spokesperson_aside(self):
        r = find_experts(fast(), text=demo.ARTICLE)
        by = {e["name"]: e for e in r["experts"]}
        self.assertEqual(set(by), {"Maren Okafor", "Tobias Wren", "Anna Price"})
        self.assertTrue(by["Maren Okafor"]["selected"])
        self.assertEqual(by["Anna Price"]["kind"], "other")
        self.assertFalse(by["Anna Price"]["selected"])

    def test_every_result_state_is_covered(self):
        r = check_article(fast(), text=demo.ARTICLE)
        by = {e["name"]: e for e in r["experts"]}
        self.assertNotIn("Anna Price", by)  # non-experts aren't checked by default

        okafor = by["Maren Okafor"]
        self.assertEqual(okafor["status"], "connections_found")
        ties = {t["org"]: t for t in okafor["ties"]}
        self.assertEqual(set(ties), {"Veltrix Pharmaceuticals", "Halden Biotech", "Orbis Labs"})
        self.assertNotIn("Corvane Biologics", ties)  # J.L.'s grant, not Okafor's
        veltrix = ties["Veltrix Pharmaceuticals"]
        self.assertTrue(veltrix["related_to_story"])
        self.assertEqual(len(veltrix["evidence"]), 2)  # paper + bio page
        self.assertEqual(veltrix["open_payments"]["status"], "name_match")
        self.assertEqual(veltrix["open_payments"]["total_usd"], 2 * 25536.4)  # same rows in both dataset years
        self.assertEqual(okafor["ties"][0]["org"], "Veltrix Pharmaceuticals")  # story-related first

        wren = by["Tobias Wren"]
        self.assertEqual(wren["status"], "identity_not_confirmed")
        self.assertEqual(len(wren["identity"]["candidates"]), 2)
        self.assertEqual(wren["ties"], [])

    def test_picking_a_candidate_confirms_and_searches(self):
        experts = [{"name": "Tobias Wren", "affiliation": "Northfield Institute of Public Health",
                    "orcid": demo.WREN_ORCIDS[0]}]
        r = check_article(fast(), text=demo.ARTICLE, experts=experts)
        wren = r["experts"][0]
        self.assertEqual(wren["identity"]["by"], "user")
        self.assertEqual(wren["status"], "connections_found")
        self.assertEqual([t["org"] for t in wren["ties"]], ["Brightwater Health Trust"])
        self.assertFalse(wren["ties"][0]["related_to_story"])

    def test_demo_loads_article_by_url_too(self):
        r = find_experts(fast(), url="https://news.example.com/new-pill")
        self.assertIn("Maren Okafor", [e["name"] for e in r["experts"]])


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.quiet = True
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.status, dict(r.headers), r.read()

    def post(self, path, body, raw=False):
        data = body if raw else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def test_page_and_cache_headers(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Conflict Check", body)
        self.assertEqual(headers["Cache-Control"], "no-cache")
        _, headers, _ = self.get("/api/config")
        self.assertIn("stale-while-revalidate", headers["Cache-Control"])
        _, _, body = self.get("/api/demo")
        self.assertIn("Maren Okafor", json.loads(body)["text"])

    def test_query_string_is_ignored(self):
        self.assertEqual(self.get("/?utm=x")[0], 200)

    def test_demo_experts_and_stream(self):
        status, body = self.post("/api/experts", {"text": demo.ARTICLE, "demo": True})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["experts"]), 3)
        status, body = self.post("/api/check/stream", {"text": demo.ARTICLE, "demo": True,
                                                        "experts": [{"name": "Maren Okafor",
                                                                     "affiliation": "Lakeside University"}]})
        events = [json.loads(line) for line in body.decode().splitlines()]
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "start")
        self.assertIn("call", types)
        self.assertEqual(types[-1], "done")
        self.assertEqual(sum(t == "expert" for t in types), 1)

    def test_bad_requests(self):
        self.assertEqual(self.post("/api/experts", b"{not json", raw=True)[0], 400)
        self.assertEqual(self.post("/api/experts", [1, 2], )[0], 400)
        status, body = self.post("/api/experts", {})
        self.assertEqual(status, 400)
        self.assertIn("article", json.loads(body)["error"])
        self.assertEqual(self.post("/api/nope", {})[0], 404)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.get("/nope")
        self.assertEqual(cm.exception.code, 404)
        cm.exception.close()

    def raw(self, request: bytes) -> bytes:
        import socket
        with socket.create_connection(("127.0.0.1", self.httpd.server_address[1]), timeout=3) as s:
            s.sendall(request)
            return s.recv(4096).split(b"\r\n")[0]

    def test_negative_or_bad_content_length_is_rejected_without_blocking(self):
        for length in (b"-1", b"abc", b"1e3"):
            status = self.raw(b"POST /api/experts HTTP/1.1\r\nHost: x\r\nContent-Length: " + length + b"\r\n\r\n{}")
            self.assertIn(b" 400 ", status, length)

    def test_oversize_body_is_413_without_reading_it(self):
        status = self.raw(b"POST /api/experts HTTP/1.1\r\nHost: x\r\nContent-Length: 3000000\r\n\r\n")
        self.assertIn(b" 413 ", status)

    def test_demo_leaves_no_files_behind(self):
        import glob, os, tempfile
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "cc-demo-*")))
        self.post("/api/experts", {"text": demo.ARTICLE, "demo": True})
        self.assertEqual(set(glob.glob(os.path.join(tempfile.gettempdir(), "cc-demo-*"))), before)
        self.assertIsNone(demo.demo_session().cache_dir)

    def test_stream_reports_errors_as_events(self):
        status, body = self.post("/api/check/stream", {"text": "", "demo": True})
        events = [json.loads(line) for line in body.decode().splitlines()]
        self.assertEqual(events[-1]["type"], "error")


if __name__ == "__main__":
    unittest.main()
