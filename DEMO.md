# Demo script

Runs with **no network and no API keys**: every Tavily, Exa, ORCID and Open Payments response for the two demo articles is saved in `demo-cache/`.

```sh
python -m conflict_check.server --replay --cache-dir demo-cache   # http://localhost:8000
```

`python tests/e2e/walk_replay.py` clicks through Article 1 below in a headless browser and checks the results (19 checks, no keys or network). Replay serves only saved answers, so stick to the two articles below. Anything else shows an error ("Not cached (replay mode)"). To rebuild the cache, run the server without `--replay` and your keys, with the same articles and experts. Open Payments lookups can take 35-40 s, and the server gives up on them at 20 s, so a rebuild may drop slow badges.

## Article 1: the Wegovy pill (Scientific American)

URL: `https://scientificamerican.com/article/wegovy-pill-becomes-first-oral-glp-1-weight-loss-drug-approved-in-u-s`

1. Paste the URL, click **Find experts**. Three people appear.
2. Set the institutions (they matter, identity is confirmed against them):
   - Daniel Drucker: University of Toronto
   - Rozalina McCoy: University of Maryland
   - John Buse: University of North Carolina at Chapel Hill
3. Click **Check**. Point at, in order:
   - **John Buse:** ties to companies the article never mentions (Eli Lilly, AstraZeneca, Johnson & Johnson, Boehringer Ingelheim, Medtronic, Dexcom). Open **Why?** to show the seven reliability factors, and the **Open Payments** badges on Eli Lilly and AstraZeneca (name matches only, with city, state and NPI so a person can judge).
   - **Rozalina McCoy:** public funders (ADA, PCORI, NIH institutes), a reminder that "tie" includes grants.
   - **Daniel Drucker:** *Identity not confirmed*. ORCID returned no single match, so the tool refuses to show ties for a possibly wrong person. This is the safety rule, not a bug.
4. Turn on **Mask names** before projecting.

## Article 2: Down syndrome and Leqembi (STAT)

URL: `https://www.statnews.com/2024/08/21/alzheimers-down-syndrome-leqembi-risks-brain-hemorrhage/`

Experts: Michael Rafii (University of Southern California), Lon Schneider (University of Southern California), Lei Liu (Brigham and Women's Hospital).

- **Lon Schneider:** a long list of company ties (Eli Lilly, Novartis, Johnson & Johnson, Eisai, Novo Nordisk, ...). Ties to companies named in the story sort first.
- **Michael Rafii:** drug-company ties, with an Open Payments name match on Ionis Pharmaceuticals.
- **Lei Liu:** identity not confirmed, same message as Drucker.

## What to say about its limits

- It finds ties that are **disclosed somewhere** (papers, bios, filings). It can't find ties nobody disclosed, and "no confirmed connections" is a normal result.
- On a hand-checked set of 15 experts it recovers about two-thirds of the labelled ties (recall 66%). The labels are incomplete, so its precision is understated, and a few results are noise (a stray organization-like phrase). A person reviews the list before anything is searched.
- About half the experts in the set (9 of 18) are declined at the identity step, on purpose.
- Open Payments matches by name, city and state, not employer, so it is shown as a badge to judge, never as a tie on its own.
