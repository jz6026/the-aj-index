"""The website's backend: look up items, check trades with trade.py, and the chatbot
(/api/chat, see chat.py). Values always come back exactly as the wiki writes them.

Run it locally:
    uvicorn ajworth.api:app --reload           # then open http://localhost:8000/docs

It reads whatever database db.default_target() picks (DATABASE_URL, or data/worth.db).
"""

from __future__ import annotations

import threading
import time
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from . import db, store
from .chat import MAX_LEN, Intents, respond
from .ladder import Ladder
from .match import Matcher
from .trade import check

WIKI = "https://aj-item-worth.fandom.com/wiki/"
CREDIT = ( "Values from the AJ Item Worth Wiki (aj-item-worth.fandom.com), shared under CC BY-SA. "
           "Unofficial fan project, not affiliated with WildWorks. Double-check before you accept a trade!" )

app = FastAPI( title="The AJ Index", docs_url="/api/docs", openapi_url="/api/openapi.json" )


def get_conn():
    """A fresh connection per request. Totally fine at our size, and nothing gets stuck
    if the database restarts."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@app.get( "/api/health" )
def health():
    # AWS pings this to check the container is alive. Keep it dumb on purpose: if it
    # also checked the database, a database hiccup would make AWS restart the app over and over
    return { "ok": True }


@app.get( "/api/items" )
def search_items( q: str = Query( ..., min_length=1, max_length=60 ), conn=Depends( get_conn ) ):
    """Item names containing q (case doesn't matter). Slang matching comes later (v1 roadmap)."""
    needle = q.strip().lower().replace( "\\", "\\\\" ).replace( "%", "\\%" ).replace( "_", "\\_" )
    rows = conn.execute(
        """SELECT title, COUNT(*) AS variants FROM current_worth
           WHERE LOWER(title) LIKE ? ESCAPE '\\'
           GROUP BY title
           ORDER BY CASE WHEN LOWER(title) = ? THEN 0 WHEN LOWER(title) LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END,
                    LENGTH(title), title
           LIMIT 20""",
        ( f"%{needle}%", q.strip().lower(), f"{needle}%" ),
    ).fetchall()
    return { "query": q, "results": [ { "title": r[ "title" ], "variants": r[ "variants" ] } for r in rows ] }


@app.get( "/api/items/{title}" )
def get_item( title: str, conn=Depends( get_conn ) ):
    """Every color/variant of one item, with the worth copied word for word from the wiki."""
    rows = conn.execute(
        """SELECT section, variant, worth_raw, last_updated FROM current_worth
           WHERE title = ? ORDER BY section, variant""",
        ( title, ),
    ).fetchall()
    if not rows:
        raise HTTPException( status_code=404, detail=f"No item called {title!r} (yet!)" )
    return {
        "title": title,
        "wiki_url": WIKI + quote( title.replace( " ", "_" ) ),
        "last_updated": rows[ 0 ][ "last_updated" ],
        "variants": [ { "section": r[ "section" ], "variant": r[ "variant" ], "worth": r[ "worth_raw" ] }
                      for r in rows ],
        "credit": CREDIT,
    }


# ---------------------------------------------------------------- trade checks

# Building the matcher + ladder reads every saved wiki page, so it's done once and reused.
# It gets rebuilt every so often, so the daily wiki refresh shows up without restarting anything.
REBUILD_EVERY = 15 * 60          # seconds
_cache = { "at": 0.0, "matcher": None, "ladder": None }
_cache_lock = threading.Lock()


def trade_tools( conn ) -> tuple[ Matcher, Ladder ]:
    with _cache_lock:
        if _cache[ "matcher" ] is None or time.time() - _cache[ "at" ] > REBUILD_EVERY:
            _cache[ "matcher" ] = Matcher.from_db( conn )
            _cache[ "ladder" ] = Ladder.from_pages( store.all_wikitext( conn ) )
            _cache[ "at" ] = time.time()
        return _cache[ "matcher" ], _cache[ "ladder" ]


@app.get( "/api/trade" )
def check_trade( q: str = Query( ..., min_length=3, max_length=300 ), conn=Depends( get_conn ) ):
    """Like `python3 -m ajworth.trade`: q is the trade as you'd type it, like "my beard for 2 blk longs"."""
    matcher, ladder = trade_tools( conn )
    return { **check( q, matcher, ladder ).to_dict(), "credit": CREDIT }


# ---------------------------------------------------------------- chatbot

_intents = Intents.load()      # my model if it's trained and beat the rules, otherwise the rules


class ChatIn( BaseModel ):
    message: str = Field( ..., min_length=1, max_length=MAX_LEN )


@app.post( "/api/chat" )
def chat( body: ChatIn, conn=Depends( get_conn ) ):
    """One message in, one reply out. Nothing gets saved (no logs of what people type yet)."""
    matcher, ladder = trade_tools( conn )
    return { **respond( body.message, matcher, ladder, _intents ).to_dict(), "credit": CREDIT }
