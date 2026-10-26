# AJ Worth Lookup

Fast Animal Jam Classic item values, pulled from the
[AJ Item Worth Wiki](https://aj-item-worth.fandom.com) through its MediaWiki API.

## Setup (Mac)

```bash
cd aj-worth
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Use

```bash
python3 -m pytest -q                      # run the tests (no internet needed)
python3 -m ajworth.fetch --limit 20       # quick test: fetch 20 pages
python3 -m ajworth.fetch                  # full refresh (a few minutes; it waits 1s between requests)
python3 -m ajworth.fetch --labels         # every worth label in use, most common first
```

Comments (the wiki's informal price log, going back years):

```bash
python3 -m ajworth.comments --titles Beard   # one item
python3 -m ajworth.comments --limit 25       # first 25 items in the database
python3 -m ajworth.comments                  # every item (slow on purpose: 1 request/second)
python3 -m ajworth.comments --sample 20      # spot-check 20 stored comments and their tags
```

Outputs:
- `data/worth.db` — SQLite database. `worth_snapshots` keeps every value ever seen,
  tagged with the wiki revision it came from. `current_worth` is the latest value per variant.
- `data/items.json` — current values as one file: the instant, offline lookup cache.

## How it works

| File | Job |
|---|---|
| `ajworth/parse.py` | Raw page source → one row per item variant (e.g. Beard / Black & White / "A Few RIMs") |
| `ajworth/fetch.py` | Lists every page in Category:Items, downloads 50 per request, skips unchanged pages |
| `ajworth/store.py` | Saves to SQLite; only writes new rows when a page actually changed, so history builds up for trend charts |
| `ajworth/comments.py` | Pages through each item's comments, scrubs usernames, stores them; re-runs only fetch what's new |
| `ajworth/tagger.py` | Rule-based tags: sale / sold / iso / trade / question, plus diamond and gem prices. The baseline a trained model has to beat |

### Comments data

- `comments` table: one row per post, with its date, scrubbed text, tag and price.
- `listings` view: sale posts, with `sold = 1` when a reply confirms the sale.

**Privacy rule:** usernames are never stored. Author fields are dropped and names are
scrubbed from the text before saving (`[user]` replaces them). Many players are kids.
Scrubbing is best effort; `--sample` is the quick way to spot-check it.

Values are stored exactly as the wiki writes them ("A Few RIMs", "1-2 Den Betas").
Converting those labels into one unit (black longs) is the next step.
