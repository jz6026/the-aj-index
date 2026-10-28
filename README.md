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
cd the-aj-index
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

## Chatbot

```bash
python3 -m ajworth.chat "my blk long for 2 bad longs"   # one message
python3 -m ajworth.chat                                 # chat back and forth
python3 -m ajworth.chat --label                         # label real messages for training
python3 -m ajworth.chat --train                         # train my intent model vs the rules
```

Starter examples live in `ajworth/chat_examples.csv` (add more anytime!). My labels go in
`data/chat_labels.csv`. The chatbot only switches to my model once it beats the rules.

## Website + database (Docker)

Needs [Docker Desktop](https://www.docker.com/products/docker-desktop/). This runs the site the
same way it runs on AWS: Postgres, the API, and the web page.

```bash
docker compose up --build -d           # start everything, then open http://localhost:8080
docker compose run --rm refresh        # pull the wiki's values into Postgres (first time: a few minutes)
docker compose logs -f api             # watch the API
docker compose down                    # stop (add -v to also wipe the database)
```

The API's auto-made docs are at http://localhost:8080/api/docs.
Everything above (fetch, comments, label) also works on Postgres: set
`DATABASE_URL=postgresql://aj:aj@localhost:5432/ajindex` or pass `--db`. Without it, it's SQLite like before.

Run the tests on Postgres too (with `docker compose up -d db` running):

```bash
TEST_DATABASE_URL=postgresql://aj:aj@localhost:5432/ajindex python3 -m pytest -q
```

Putting it on AWS: see [DEPLOY.md](DEPLOY.md).

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
| `ajworth/chat.py` | The chatbot: my own intent model (or the rules until it wins) decides what a message wants, then trade.py answers. Blocks usernames/contact info |
| `ajworth/db.py` | Opens SQLite or Postgres, so the same code runs on my Mac and on AWS |
| `ajworth/api.py` | The website's backend (FastAPI): item search, item lookup, and `/api/trade` (runs trade.py). Chatbot goes here later |
| `web/` | Placeholder page (design TBD!) + the local nginx setup that stands in for CloudFront |
| `infra/` | The AWS setup as code (CDK), see DEPLOY.md |

### Comments data

- `comments` table: one row per post, with its date, scrubbed text, tag and price.
- `listings` view: sale posts, with `sold = 1` when a reply confirms the sale.

**Privacy rule:** usernames scraped from the wiki are never stored. Author fields are dropped and names are
scrubbed from the text before saving (`[user]` replaces them). Many players are kids.
Scrubbing is best effort; `--sample` is the quick way to spot-check it.

Values are stored exactly as the wiki writes them ("A Few RIMs", "1-2 Den Betas").
Converting those labels into one unit (black longs) is the next step.
