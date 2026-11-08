"""Browser walk-through of DEMO.md: real article, real saved responses, no network and no API keys.

    python tests/e2e/walk_replay.py [screenshot-dir]

Starts a private server in replay mode on demo-cache/, then clicks through the Wegovy-pill article like a
person would: find experts, fix the affiliations, check, read the results. Not part of `python -m unittest`
(it needs a browser). Fails if any request misses the cache, because replay would then show an error.
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SP = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="cc-replay-shots-")
URL = "https://scientificamerican.com/article/wegovy-pill-becomes-first-oral-glp-1-weight-loss-drug-approved-in-u-s"
AFF = {"Daniel Drucker": "University of Toronto", "Rozalina McCoy": "University of Maryland",
       "John Buse": "University of North Carolina at Chapel Hill"}

with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
env = {k: v for k, v in os.environ.items() if k not in ("TAVILY_API_KEY", "EXA_API_KEY")}
env["CC_NO_DOTENV"] = "1"  # no keys at all: a live call would fail, so only the cache can answer
server = subprocess.Popen([sys.executable, "-m", "conflict_check.server", "--port", str(port), "--replay",
                           "--cache-dir", os.path.join(ROOT, "demo-cache")], cwd=ROOT, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
BASE = f"http://127.0.0.1:{port}/"
for _ in range(40):
    try:
        json.load(urllib.request.urlopen(BASE + "api/config", timeout=2)); break
    except Exception:
        time.sleep(0.25)
else:
    server.kill(); raise SystemExit("server did not start")

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


b = Browser()
try:
    b.goto(BASE)
    b.js("localStorage.clear()")
    b.goto(BASE)
    check("page loads, no JS errors", b.js("!!document.getElementById('find')") and not b.errors(), "; ".join(b.errors()))

    # --- step 1: find experts ---
    b.js("document.getElementById('url').value = %s; document.getElementById('find').click()" % json.dumps(URL))
    check("three experts found", b.wait("document.querySelectorAll('#rows .person:not(.skeleton)').length === 3", 20),
          str(b.js("document.getElementById('msg').textContent")))
    names = b.js("[...document.querySelectorAll('#rows input[data-k=name]')].map(i => i.value)")
    check("Drucker, McCoy and Buse listed", set(names) == set(AFF), str(names))

    # --- the person fixes the institutions (what DEMO.md says to do) ---
    for name, aff in AFF.items():
        b.js("""(() => { const row = [...document.querySelectorAll('#rows .person')].find(p => p.querySelector('input[data-k=name]').value === %s);
                const f = row.querySelector('input[data-k=affiliation]'); f.value = %s; f.dispatchEvent(new Event('input', {bubbles: true})); })()""" % (json.dumps(name), json.dumps(aff)))
    b.js("document.getElementById('review').scrollIntoView()"); time.sleep(0.3); b.shot(SP + "/replay-1-review.png")

    # --- step 2: check ---
    b.js("document.getElementById('check-btn').click()")
    check("pending cards appear", b.wait("document.querySelector('.result.pending')", 5))
    check("run finishes with next actions", b.wait("!document.getElementById('result-actions').hidden", 60))
    status = b.js("Object.fromEntries([...document.querySelectorAll('.result')].map(c => [c.dataset.card, c.querySelector('.chip').className.replace('chip ', '')]))")
    check("Buse: connections found", status.get("John Buse") == "connections_found", str(status))
    check("McCoy: connections found", status.get("Rozalina McCoy") == "connections_found", str(status))
    check("Drucker: confirmed through OpenAlex", status.get("Daniel Drucker") == "connections_found", str(status))
    check("no error cards", "error" not in status.values(), str(status))
    calls = b.js("[...document.querySelectorAll('#calls .call .meta')].map(m => m.className.replace('meta ', ''))")
    check("every API call came from the cache", calls and set(calls) == {"cache"}, str(sorted(set(calls))))

    buse = "[data-card='John Buse']"
    orgs = b.js("[...document.querySelectorAll(\"" + buse + " .tie\")].map(t => t.querySelector('b').textContent)")
    check("Buse lists Eli Lilly and AstraZeneca", {"Eli Lilly", "AstraZeneca"} <= set(orgs), str(orgs))
    check("Open Payments badge shown for Buse", b.js("!!document.querySelector(\"" + buse + " .op b\")"))
    check("every tie has a reliability pill", b.js("[...document.querySelectorAll(\"" + buse + " .tie\")].every(t => !!t.querySelector('.rel'))"))
    b.js("document.querySelector(\"" + buse + " .tie details.why\").open = true")
    check("'Why?' lists the seven factors", b.js("document.querySelector(\"" + buse + " .tie details.why .factors\").children.length") == 7)
    check("coverage rating shown", b.js("!!document.querySelector(\"" + buse + " .coverage .rel\")"))
    check("Drucker card says how identity was confirmed", b.js("!!document.querySelector(\"[data-card='Daniel Drucker']\").innerText.match(/OpenAlex/i)"))
    b.js("document.getElementById('results-block').scrollIntoView()"); time.sleep(0.3); b.shot(SP + "/replay-2-results.png")
    b.js("document.querySelector(\"" + buse + "\").scrollIntoView()"); time.sleep(0.3); b.shot(SP + "/replay-3-buse.png")

    # --- mask names, as DEMO.md says to do before projecting ---
    b.js("document.getElementById('mask').click()")
    check("mask hides every name", b.wait("![...document.querySelectorAll('#results, #rows, #calls')].some(e => /Buse|McCoy|Drucker/.test(e.innerText))", 3))
    b.shot(SP + "/replay-4-masked.png")
    b.js("document.getElementById('mask').click()")
    check("no JS errors during the walk", not b.errors(), "; ".join(b.errors()))
finally:
    b.close()
    server.kill()

print(f"\n{sum(results)}/{len(results)} passed · screenshots in {SP}")
sys.exit(0 if all(results) else 1)
