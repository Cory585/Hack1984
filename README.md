# Hack1984 · Conflict Check

**Who pays the experts an article quotes.** Paste a health news article. For each quoted expert, Conflict Check confirms who they are, then searches papers and the web for funding, consulting and board ties *the article didn't mention*, quoting the source for every one.

Surge track (Tavily + Exa). This is the project framework; see the build plan below for what's left.

## Run it

Python 3.10+ with no third-party packages.

```sh
cp .env.example .env            # add TAVILY_API_KEY and EXA_API_KEY
python -m conflict_check.server # http://localhost:8000
python -m conflict_check.server --replay   # demo mode: cached responses only, no network
python -m unittest              # offline tests (fictional fixtures)
python -m eval.run_eval         # score against eval/testset.json
```

## How it works

| Step | Module | API |
|---|---|---|
| Load the article (URL or pasted text) | `pipeline.load_article` | Tavily extract |
| Pull out quoted experts, their role and affiliation (max 5) | `extract.py` | none, rule-based |
| Confirm identity: exactly one ORCID record for name + article affiliation | `identity.py` | ORCID public API |
| Find evidence pages: research papers (conflict statements) and web bios | `pipeline.gather_pages` | Exa research-paper search, Tavily search + extract |
| Extract ties: a clause naming the person, an org, and a tie keyword | `ties.find_ties` | none, rule-based |
| Classify: disclosed in article / related to this story / other | `ties.classify_tie` | none |

Every call goes through `session.Session`, which caches responses to `cache/` (keyed by request, never storing keys), supports replay mode, and logs calls for the UI's **API calls** panel.

## Safety rules (from the risk review)

- **No identity, no ties.** If ORCID doesn't return exactly one match for name + affiliation, the expert shows *Identity not confirmed* and nothing else.
- **No model states a tie.** A tie appears only if a fetched page has a clause naming both the person and the organization, and `verify_quote` confirms the quote is on that page.
- **Declining is a valid result.** *No confirmed connections* is a normal outcome.
- **The wording is "connections the article didn't mention",** not "undisclosed conflicts" or "hidden ties".
- **Mask names** in the UI for the on-stage demo. Only demo on hand-checked articles, plus one control article that should find nothing.
- **Scope:** health news, where papers carry conflict statements.

## Build plan / TODO

- [ ] Hour-1 test: run 3–5 real health articles live; tune `extract.py` and `ties.py` patterns.
- [ ] One-click identity confirmation in the UI when ORCID returns several candidates.
- [ ] Stream API calls to the panel as they happen (SSE) rather than after the run.
- [ ] CMS Open Payments as a confirmation badge for US physicians (not a sponsor API, so secondary).
- [ ] Build a ~20-article test set in `eval/testset.json`; put precision and decline rate on one slide. Cite CMAJ 2017 (PMC5392116): about a third of commenters had financial conflicts, and two-thirds went unreported.
- [ ] Demo: curated replay cache, backup video, limitations slide.
