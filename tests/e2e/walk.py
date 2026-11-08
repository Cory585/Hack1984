"""End-to-end walk through the real page, clicking like a user, in headless Edge/Chrome.

    python -m conflict_check.server            # in one terminal
    python tests/e2e/walk.py [base-url] [screenshot-dir]

Uses the built-in demo, so no API keys are needed (one step checks the
no-keys error path, so leave TAVILY/EXA keys unset). Not part of
`python -m unittest`, since it needs a browser and a running server.
"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Browser

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/"
SP = sys.argv[2] if len(sys.argv) > 2 else tempfile.mkdtemp(prefix="cc-e2e-shots-")
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))


b = Browser()
try:
    b.goto(BASE)
    b.js("localStorage.clear()")
    b.goto(BASE)
    check("page loads, no JS errors", b.js("!!document.getElementById('demo-btn')") and not b.console, "; ".join(b.console))

    # --- dead end: empty submit ---
    b.js("document.getElementById('find').click()")
    check("empty submit explains what to do", b.wait("document.getElementById('msg').textContent.includes('link')", 3))

    # --- dead end: live search with no API keys -> error box with fixes ---
    b.js("document.getElementById('url').value = 'https://news.example.com/x'; document.getElementById('find').click()")
    check("button shows loading shine", b.wait("document.getElementById('find').classList.contains('loading') || document.querySelector('#rows .error-box')", 3))
    ok = b.wait("document.querySelector('#rows .error-box')", 15)
    btns = b.js("[...document.querySelectorAll('#rows .error-box button')].map(x => x.textContent.trim())") if ok else []
    check("failed search offers Try again + demo", ok and "Try again" in btns and "Use the demo instead" in btns, str(btns))

    # --- demo from the error box ---
    b.js("[...document.querySelectorAll('#rows .error-box button')].find(x => x.textContent.includes('demo')).click()")
    check("review shows skeleton rows while loading", b.wait("document.querySelector('#rows .person.skeleton') || document.querySelectorAll('#rows .person:not(.skeleton)').length", 5))
    check("demo finds 3 people", b.wait("document.querySelectorAll('#rows .person:not(.skeleton)').length === 3", 15))
    check("demo badge visible", b.js("!document.getElementById('demo-badge').hidden"))
    check("spokesperson unticked", b.js("[...document.querySelectorAll('#rows .person')].filter(p => !p.querySelector('.check').checked).length === 1"))
    b.js("document.getElementById('review').scrollIntoView()"); time.sleep(0.3); b.shot(SP + "/e2e-1-review.png")

    # --- run the check: skeleton cards + stepper, then results ---
    b.js("document.getElementById('check-btn').click()")
    check("pending cards show skeleton + stepper", b.wait("document.querySelector('.result.pending .steps') && document.querySelector('.result.pending .skel')", 5))
    saw_active = b.wait("document.querySelector('.stp.active') || document.querySelector('.stp.done')", 8)
    check("stepper advances with API calls", saw_active)
    b.js("document.getElementById('results-block').scrollIntoView()"); time.sleep(0.2); b.shot(SP + "/e2e-2-checking.png")
    check("API panel streams calls", b.wait("document.querySelectorAll('#calls .call .api').length >= 3", 15))
    check("run finishes with next actions", b.wait("!document.getElementById('result-actions').hidden", 40))
    statuses = b.js("Object.fromEntries([...document.querySelectorAll('.result')].map(c => [c.dataset.card, c.querySelector('.chip').className.replace('chip ', '')]))")
    check("Okafor: connections found", statuses.get("Maren Okafor") == "connections_found", str(statuses))
    check("Wren: identity not confirmed", statuses.get("Tobias Wren") == "identity_not_confirmed", str(statuses))
    check("Open Payments badge shown", b.js("!!document.querySelector('.op b')"))
    b.js("document.getElementById('results-block').scrollIntoView()"); time.sleep(0.2); b.shot(SP + "/e2e-3-results.png")

    # --- pick a candidate ---
    b.js("document.querySelector('[data-card=\"Tobias Wren\"] button[data-orcid]').click()")
    check("picked expert re-checks in place", b.wait("document.querySelector('[data-card=\"Tobias Wren\"].pending')", 3))
    check("pick confirms + finds tie", b.wait("document.querySelector('[data-card=\"Tobias Wren\"] .chip.connections_found')", 20))
    check("Okafor card untouched by single re-run", b.js("!!document.querySelector('[data-card=\"Maren Okafor\"] .chip.connections_found')"))

    # --- stale-while-revalidate on a second run ---
    b.js("document.getElementById('check-btn').click()")
    stale = b.wait("document.querySelector('.result.stale') && !document.getElementById('banner').hidden", 3)
    check("re-run shows last result instantly (stale)", stale, b.js("document.getElementById('banner').textContent"))
    check("stale cards refresh to fresh", b.wait("!document.querySelector('.result.stale') && !document.getElementById('result-actions').hidden", 40))
    check("banner says up to date", b.js("document.getElementById('banner').textContent.includes('Up to date') || document.getElementById('banner').hidden"))

    # --- result actions ---
    b.js("document.querySelector('[data-act=download]').click()")
    check("download gives feedback", b.wait("document.getElementById('toast').textContent.includes('downloaded')", 3))
    b.js("document.querySelector('[data-act=copy]').click()")
    check("copy gives feedback (copied or fallback)", b.wait("/copied|Couldn't copy/.test(document.getElementById('toast').textContent)", 3))

    # --- How it works: view transition expand / collapse ---
    b.js("document.getElementById('how').scrollIntoView()")
    has_vt = b.js("typeof document.startViewTransition === 'function'")
    w0 = b.js("document.querySelectorAll('.how-card')[2].getBoundingClientRect().width")
    b.js("document.querySelectorAll('.how-toggle')[2].click()")
    check("card expands to full width", b.wait("document.querySelectorAll('.how-card')[2].classList.contains('expanded') && document.querySelectorAll('.how-card')[2].getBoundingClientRect().width > " + str(w0 * 2), 3),
          f"view transitions supported: {has_vt}")
    check("expanded card shows more + aria-expanded", b.js("!document.getElementById('how-more-3').hidden && document.querySelectorAll('.how-toggle')[2].getAttribute('aria-expanded') === 'true'"))
    time.sleep(0.5); b.js("document.querySelectorAll('.how-card')[2].scrollIntoView({block: 'center'})"); time.sleep(0.2); b.shot(SP + "/e2e-4-how.png")
    b.js("document.querySelectorAll('.how-toggle')[0].click()")
    check("opening another closes the first", b.wait("document.querySelectorAll('.how-card.expanded').length === 1 && document.querySelectorAll('.how-card')[0].classList.contains('expanded')", 3))
    b.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    check("Esc collapses", b.wait("!document.querySelector('.how-card.expanded')", 3))
    b.js("document.querySelectorAll('.how-toggle')[1].click()")
    b.wait("document.querySelector('.how-card.expanded')", 3); time.sleep(0.5)
    b.js("document.querySelector('.how-card.expanded [data-act=close-card]').click()")
    check("Close button collapses", b.wait("!document.querySelector('.how-card.expanded')", 3))

    # --- Limits: same expandable behaviour, independent of How it works ---
    b.js("document.getElementById('limits').scrollIntoView()")
    lw0 = b.js("document.querySelectorAll('#limits-grid .how-card')[1].getBoundingClientRect().width")
    b.js("document.querySelectorAll('.how-toggle')[0].click()")   # open a How card too
    b.wait("document.querySelector('#how-grid .how-card.expanded')", 3); time.sleep(0.5)
    b.js("document.querySelectorAll('#limits-grid .how-toggle')[1].click()")
    check("limit card expands to full width", b.wait("document.querySelectorAll('#limits-grid .how-card')[1].classList.contains('expanded') && document.querySelectorAll('#limits-grid .how-card')[1].getBoundingClientRect().width > " + str(lw0 * 2), 3))
    check("limit shows more + aria-expanded", b.js("!document.getElementById('lim-more-2').hidden && document.querySelectorAll('#limits-grid .how-toggle')[1].getAttribute('aria-expanded') === 'true'"))
    check("sections are independent (How card stays open)", b.js("!!document.querySelector('#how-grid .how-card.expanded')"))
    time.sleep(0.5); b.js("document.querySelectorAll('#limits-grid .how-card')[1].scrollIntoView({block: 'center'})"); time.sleep(0.2); b.shot(SP + "/e2e-5-limits.png")
    b.js("document.querySelectorAll('#limits-grid .how-toggle')[3].click()")
    check("opening another limit closes the first", b.wait("document.querySelectorAll('#limits-grid .how-card.expanded').length === 1 && document.querySelectorAll('#limits-grid .how-card')[3].classList.contains('expanded')", 3))
    time.sleep(0.5)
    b.js("document.querySelectorAll('#limits-grid .how-toggle')[3].focus(); document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))")
    check("Esc closes the focused section's card", b.wait("!document.querySelector('#limits-grid .how-card.expanded') && document.querySelector('#how-grid .how-card.expanded')", 3))
    b.js("document.querySelectorAll('#limits-grid .how-toggle')[0].click()"); b.wait("document.querySelector('#limits-grid .how-card.expanded')", 3); time.sleep(0.5)
    b.js("document.querySelector('#limits-grid .how-card.expanded [data-act=close-card]').click()")
    check("limit Close button collapses", b.wait("!document.querySelector('#limits-grid .how-card.expanded')", 3))
    b.js("document.querySelector('#how-grid .how-card.expanded [data-act=close-card]').click()")
    b.wait("!document.querySelector('.how-card.expanded')", 3)

    # --- mask names, exit demo, check another ---
    b.js("document.getElementById('mask').click()")
    check("mask hides names everywhere", b.wait("![...document.querySelectorAll('#results, #rows, #calls')].some(e => e.innerText.includes('Okafor'))", 3), b.js("[...document.querySelectorAll('#results *, #rows *, #calls *')].filter(e => !e.children.length && e.textContent.includes('Okafor')).map(e => e.className + ':' + e.textContent.slice(0,60)).join(' | ')"))
    b.js("document.getElementById('mask').click()")
    b.js("document.querySelector('[data-act=new]').click()")
    ok = b.wait("Math.abs(document.getElementById('check').getBoundingClientRect().top) < 120", 3)
    check("'Check another article' returns to the input", ok, str(b.js("[document.getElementById('check').getBoundingClientRect().top, scrollY, document.documentElement.scrollHeight, innerHeight, document.activeElement.id]")))
    b.js("document.querySelector('[data-act=exit-demo]').click()")
    check("exit demo clears demo mode", b.wait("document.getElementById('demo-badge').hidden && !document.getElementById('replay').disabled", 3))

    check("no JS errors during the walk", not b.console, "; ".join(b.console))
finally:
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
