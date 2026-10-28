# The AJ Index

Quick trade help for Animal Jam Classic, so you're not frantically searching the worth wiki
while someone's waiting on you. Everything comes from the
[AJ Item Worth Wiki](https://aj-item-worth.fandom.com) (pulled through its API).
Check out [ROADMAP.md](ROADMAP.md) for where this is going.

> Just a fan project, not affiliated with WildWorks. All the values come from the
> AJ Item Worth Wiki and its editors, whose work is shared under
> [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/). Huge thanks to them!

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

Check a trade (the core of the chatbot):

```bash
python3 -m ajworth.trade "my leap year beard for their pink beard"
python3 -m ajworth.trade "their solid for my purple long + red long"
python3 -m ajworth.trade "my blk long for 2 bad longs" --json    # JSON for the website
python3 -m ajworth.match "lb beard"                              # just find an item
```

The value ladder (built from the wiki's own counter pages, so run the full fetch first):

```bash
python3 -m ajworth.ladder                                   # the ladder, cheapest first
python3 -m ajworth.ladder --place "3 Bad Long Wrists"       # where one label sits
python3 -m ajworth.ladder --compare "Black Short Collar" "Bad Long Collar"
python3 -m ajworth.ladder --check                           # labels it can't place yet
```

Comments (the wiki's informal price log, going back years):

```bash
python3 -m ajworth.comments --titles Beard   # one item
python3 -m ajworth.comments --limit 25       # first 25 items in the database
python3 -m ajworth.comments                  # every item (slow on purpose: 1 request/second)
python3 -m ajworth.comments --sample 20      # spot-check 20 stored comments and their tags
```

My own comment classifier (needs comments collected first):

```bash
python3 -m ajworth.label                 # label comments by hand; Enter = agree with the guess
python3 -m ajworth.label --stats         # how many of each label so far
python3 -m ajworth.train --explain       # train, score vs the rules, show what it learned
python3 -m ajworth.train --try "pink and yellow for ur art easel?"
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
| `ajworth/ladder.py` | Reads the wiki's counter pages (RIMs, betas, spikes) and lines every worth label up by the wiki's own prices, so the chatbot can say higher / lower / close |
| `ajworth/match.py` | Finds items from what people type: slang list (add to `SLANG`!), the wiki's own nicknames, small typos. Asks "which color?" only when colors are worth different things |
| `ajworth/trade.py` | Splits a trade into give/get, quotes the wiki word for word, and gives a short verdict plus warnings |
| `ajworth/comments.py` | Pages through each item's comments, scrubs usernames, stores them; re-runs only fetch what's new |
| `ajworth/tagger.py` | Rule-based tags: sale / sold / iso / trade / question, plus diamond and gem prices. The baseline a trained model has to beat |
| `ajworth/label.py` | Quick hand-labeling, one comment at a time, saved to `data/labels.csv` |
| `ajworth/train.py` | My classifier: word + letter-chunk counts → logistic regression, tested on held-out labels against the rules |

### Comments data

- `comments` table: one row per post, with its date, scrubbed text, tag and price.
- `listings` view: sale posts, with `sold = 1` when a reply confirms the sale.

**Privacy rule:** usernames are never stored. Author fields are dropped and names are
scrubbed from the text before saving (`[user]` replaces them). Many players are kids.
Scrubbing is best effort; `--sample` is the quick way to spot-check it.

Values are stored exactly as the wiki writes them ("A Few RIMs", "1-2 Den Betas").
Converting those labels into one unit (black longs) is the next step.
