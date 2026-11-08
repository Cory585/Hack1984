# Demo script

Runs with **no network and no API keys**: every Tavily, Exa, ORCID and Open Payments response for the two demo articles is saved in `demo-cache/`.

```sh
python -m conflict_check.server --replay --cache-dir demo-cache   # http://localhost:8000
```

`python tests/e2e/walk_replay.py` clicks through Article 1 below in a headless browser and checks the results (18 checks, no keys or network). Replay serves only saved answers, so stick to the two articles below. Anything else shows an error ("Not cached (replay mode)"). To rebuild the cache, run the server without `--replay` and your keys, with the same articles and experts. Open Payments badges are looked up by NPI through the NPI registry (about 2 s).

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
   - **Daniel Drucker:** four ORCID records share the name and none lists Toronto, so ORCID alone can't decide. OpenAlex shows only one of them publishes from the University of Toronto, which confirms him (the card says so). Four people with the same name is exactly the case where an unconfirmed match would be a false accusation.
4. Turn on **Mask names** before projecting.

## Article 2: Down syndrome and Leqembi (STAT)

URL: `https://www.statnews.com/2024/08/21/alzheimers-down-syndrome-leqembi-risks-brain-hemorrhage/`

Experts: Michael Rafii (University of Southern California), Lon Schneider (University of Southern California), Lei Liu (Brigham and Women's Hospital).

- **Lon Schneider:** a long list of company ties (Eli Lilly, Novartis, Johnson & Johnson, Eisai, Novo Nordisk, ...). Ties to companies named in the story sort first.
- **Michael Rafii:** drug-company ties, with an Open Payments name match on Ionis Pharmaceuticals.
- **Lei Liu:** *Identity not confirmed*. Neither ORCID nor OpenAlex singles out one person, so the tool refuses to show ties for a possibly wrong person. This is the safety rule, not a bug. (To show it in Article 1 instead, clear Drucker's institution.)

## What to say about its limits

- It finds ties that are **disclosed somewhere** (papers, bios, filings). It can't find ties nobody disclosed, and "no confirmed connections" is a normal result.
- On a hand-checked set of 15 experts it recovers about two-thirds of the labelled ties (recall 66%). The labels are incomplete, so its precision is understated, and a few results are noise (a stray organization-like phrase). A person reviews the list before anything is searched.
- Some experts are declined at the identity step, on purpose: when ORCID and OpenAlex can't single out one person, nothing is searched.
- Open Payments matches by name, city and state, not employer, so it is shown as a badge to judge, never as a tie on its own.
