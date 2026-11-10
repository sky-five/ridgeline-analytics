# Outbound notes for the top lead-score decile

A rep calling new trial accounts wants a short first note that says something true about what the account
did. This module drafts one note per lead from the lead's own data and checks every note before a rep sees it.

> **All data is synthetic**, from the simulated roofing-software business in
> [saas-world-sim](https://github.com/sky-five/saas-world-sim) v0.4.0.

```bash
python scripts/run_all.py --fresh --as-of 2026-06-30   # build the warehouse on the fixed snapshot
python -m outbound_notes                               # write results/notes-template.json (no model)
python -m outbound_notes --check                       # template notes up to date, recorded drafts replay (CI)
python -m outbound_notes --record --provider gemini    # draft with a model (needs GEMINI_API_KEY)
```

## Who gets a note

Accounts in the top decile of the lead score (`fct_pqa_scores`, logistic regression on first-14-day signals)
that are on the call list: signed up 14 to 45 days ago and not paying yet. On the 2026-06-30 snapshot that is
25 leads.

## How it works

| File | What it does |
|---|---|
| `leads.py` | Loads the leads and builds each one's facts: company name, how they found us, crew size, days since signup, first-14-day counts (proposals, measurement orders, signed proposals, logins, active days) and the score's top reasons. A short hash of the facts is stored with every draft. |
| `draft.py` | Two drafters. `template` needs no model: greeting, up to two of the lead's top reasons written as sentences when the counts back them, one question. `model_draft` sends the same facts (no score, no account id) and a short rule list to any `analyst.llm` client. |
| `check.py` | Fails a note that is outside 40-90 words, doesn't name the company, doesn't end with a question, quotes a number (digits or words) that is not one of the lead's facts, mentions an activity or channel the lead has no fact for (a signed proposal when nothing was signed), mentions the score or a selection, offers money or a deadline, or leaves a `[placeholder]`. |
| `notes.py` | Drafts and checks every lead, records model drafts with the checker's verdict (failing drafts are kept), and replays a recording: the leads must be today's list, each lead's facts must hash the same, and the checker must give the same verdict. |

Limits, pinned in the tests: the checker reads words, not meaning, so "you didn't send a proposal" passes the
proposal rule for a lead that sent one, and a number that happens to equal another of the lead's counts passes.

## Results on the 2026-06-30 snapshot

| Drafter | Notes | Pass the checker | Numbers checked | Words |
|---|---|---|---|---|
| Template (no model) | 25 | 25 | 93 | 41-55 |
| Gemini `gemini-3.5-flash-lite`, free tier, recorded 2026-11-10 | 25 | 23 | 106 | 60-83 |

The Gemini drafts were recorded once through [record-notes.yml](../.github/workflows/record-notes.yml) (25
requests, about 2,300 output tokens in all) and are committed in
[results/](results/notes-gemini-gemini-3.5-flash-lite.json), so `--check` replays them with no key. The two
drafts that fail end with an offer after the question, not with the question. Two more were first flagged for
"week 1", which the checker read as an unsupported number; it now accepts "week 1" when the lead did send a
proposal in week 1, and `--rescore` re-ran the checker on the stored drafts without changing their text.
Another model will write different drafts and score differently.

Tests: `tests/outbound_notes/test_notes.py` (template, each checker rule, recording and replay with a fake
client; no warehouse or key) and `tests/outbound_notes/test_warehouse.py` (the call list matches the score mart,
every template note passes on the built warehouse). CI runs `python -m outbound_notes --check` on the snapshot.
