"""Collects the comment sections on item pages, which are basically the wiki's price log.

Most comments are shop listings ("Yellow for 1 dim at my shop"), people looking
for stuff ("ISO light brown"), and "Sold!" replies. That's years of real prices,
which is exactly what we need to learn item values later.

Usage (from the project folder, after `python3 -m ajworth.fetch`):
    python3 -m ajworth.comments --titles Beard      # one item
    python3 -m ajworth.comments --limit 25          # first 25 items in the database
    python3 -m ajworth.comments                     # every item (slow, be patient lol)
    python3 -m ajworth.comments --sample 20         # print 20 stored comments with their tags

PRIVACY: we never save usernames. Who posted is thrown away, and names get
scrubbed out of the text before anything is saved (see scrub_names). Lots of
AJ players are kids, so this one's a hard rule.

Running it again only grabs what's new: for each item it re-checks the last
RECHECK_DAYS of comments (in case someone replied "Sold!" late) and stops there.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Iterator

from . import store
from .fetch import Wiki
from .tagger import tag

COMMENTS_URL = "https://aj-item-worth.fandom.com/wikia.php"
RECHECK_DAYS = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS comments (
    post_id     TEXT PRIMARY KEY,
    thread_id   TEXT NOT NULL,
    title       TEXT NOT NULL,          -- which item page it's on
    is_reply    INTEGER NOT NULL,       -- 0 = normal comment, 1 = reply
    created     TEXT NOT NULL,          -- when it was posted (UTC)
    text        TEXT NOT NULL,          -- usernames already removed
    upvotes     INTEGER,
    -- quick guesses from the rules (see tagger.py), my model can take over later
    kind        TEXT,                   -- sale | iso | sold | trade | question | other
    diamonds    REAL,                   -- the price in diamonds, if there is one
    gems        REAL,                   -- the price in gems, if there is one
    fetched_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_title ON comments (title, created);

CREATE TABLE IF NOT EXISTS comment_progress (
    title       TEXT PRIMARY KEY,
    newest      TEXT,                   -- the newest comment date we've seen
    total_count INTEGER,
    fetched_at  TEXT
);

-- A listing counts as confirmed if someone replied that it sold.
CREATE VIEW IF NOT EXISTS listings AS
SELECT c.post_id, c.thread_id, c.title, c.created, c.text, c.diamonds, c.gems,
       EXISTS (SELECT 1 FROM comments r
               WHERE r.thread_id = c.thread_id AND r.is_reply = 1 AND r.kind = 'sold') AS sold
FROM comments c
WHERE c.is_reply = 0 AND c.kind = 'sale';
"""


# ---------------------------------------------------------------- cleaning up text

def doc_text( json_model: str ) -> str:
    """Fandom saves comments as a JSON document thing. This turns it back into plain text."""
    try:
        doc = json.loads( json_model )
    except ( TypeError, ValueError ):
        return ""

    def walk( node ) -> str:
        if node.get( "type" ) == "text":
            return node.get( "text", "" )
        parts = [ walk( c ) for c in node.get( "content", [] ) ]
        sep = "\n" if node.get( "type" ) in ( "doc", "bulletList", "orderedList" ) else " "
        return sep.join( p for p in parts if p )

    return re.sub( r"[ \t]+", " ", walk( doc ) ).strip()


_SIGNATURE_TAIL = re.compile(
    r"""(
        \s*[-–—~]+\s*[^\s\-–—~]{2,30}\s*$          # "... - Name"  /  "...-Name"
      | \s*(?:@|\bat\b|\bon\b)\s*[A-Za-z0-9_.ø]{3,30}\s*[!.)]*\s*$   # "... at name" / "@ name"
    )""",
    re.VERBOSE | re.IGNORECASE,
)
_LABELLED = re.compile( r"\b(user(?:name)?|ign|aj|shop)\s*(?:[:=]|\bis\b)\s*\S+", re.IGNORECASE )
# a line that's just one username-looking word (someone signing their post):
# it has a number, an underscore, or a capital in the middle ("ExtraFishy", "wolf_99")
_LONE_HANDLE = re.compile( r"^\s*-?\s*(?=[A-Za-z0-9_.ø]*(?:\d|_|[a-z][A-Z]))[A-Za-z0-9_.ø]{4,30}\s*$",
                          re.MULTILINE )
_AT_MENTION = re.compile( r"@\s*[A-Za-z0-9_.ø]{2,30}" )
# "jag Name", "buddy Name", "add Name" (but "jag me" is fine)
_CONTACT = re.compile( r"\b(jag|buddy|add|msg|message)\s+(?!(?:me|you|u|him|her|them|for)\b)"
                      r"[A-Za-z0-9_.ø]{3,30}", re.IGNORECASE )
# one word in parentheses at the end of a line: "... in my shop (name)"
_PAREN_TAIL = re.compile( r"\(\s*[A-Za-z0-9_.ø]{3,30}\s*\)\s*$", re.MULTILINE )
_KEEP_IN_PARENS = { "sold", "edit", "edited", "nm", "nonmember", "member", "rare", "update",
                   "updated", "taken", "found", "pending", "traded", "bought" }
# normal words people end sentences with, so we don't think they're usernames
_SAFE_TAIL_WORDS = { "shop", "store", "sale", "me", "it", "them", "please", "pls", "thanks",
                    "here", "there", "now", "today", "offer", "offers", "trade", "trades",
                    "dim", "dims", "diamonds", "diamond", "sapphire", "sapphires" }


def scrub_names( text: str, known_names: set[ str ] ) -> str:
    """Takes out usernames: the posters' own names anywhere, @mentions, 'user: x',
    and sign-offs at the end like '- name' or 'at name'.

    It's not perfect, so it'd rather remove one word too many than miss a name.
    """
    for name in sorted( known_names, key=len, reverse=True ):
        if len( name ) >= 3:
            text = re.sub( re.escape( name ), "[user]", text, flags=re.IGNORECASE )
    text = _LABELLED.sub( r"\1: [user]", text )
    text = _AT_MENTION.sub( "@[user]", text )
    text = _CONTACT.sub( r"\1 [user]", text )
    text = _LONE_HANDLE.sub( "[user]", text )
    text = _PAREN_TAIL.sub(
        lambda m: m.group( 0 ) if m.group( 0 ).strip( "() \n" ).lower() in _KEEP_IN_PARENS else "[user]", text )

    lines = []
    for line in text.splitlines():
        m = _SIGNATURE_TAIL.search( line )
        if m:
            last_word = re.findall( r"[A-Za-z0-9_.ø]+", m.group( 0 ) )
            if last_word and last_word[ -1 ].lower() not in _SAFE_TAIL_WORDS \
                    and not last_word[ -1 ].isdigit():
                line = line[ : m.start() ] + " [user]"
        lines.append( line.rstrip() )
    return re.sub( r"(\[user\]\s*){2,}", "[user] ", "\n".join( lines ) ).strip()


# ---------------------------------------------------------------- grabbing comments

def _iso( epoch: int ) -> str:
    return datetime.fromtimestamp( epoch, timezone.utc ).isoformat( timespec="seconds" )


def comment_pages( wiki: Wiki, title: str ) -> Iterator[ dict ]:
    """Goes through one item's comments page by page, newest first."""
    page = 0
    while True:
        data = wiki.get_json( COMMENTS_URL, {
            "controller": "ArticleCommentsController", "method": "getComments",
            "namespace": 0, "title": title, "hideDeleted": "true", "page": page,
        } )
        yield data
        if not data.get( "threads" ) or "next" not in ( data.get( "links" ) or {} ):
            return
        page += 1


def rows_from_thread( title: str, thread: dict, now: str ) -> list[ tuple ]:
    posts = [ ( thread[ "firstPost" ], 0 ) ] + [ ( p, 1 ) for p in thread.get( "posts", [] ) ]
    # Grab every poster's name in the thread so we can scrub it from all the
    # posts (people sign their own name and talk to each other by name).
    names = { ( p.get( "createdBy" ) or {} ).get( "name", "" ) for p, _ in posts } - { "" }

    rows = []
    for post, is_reply in posts:
        text = scrub_names( doc_text( post.get( "jsonModel", "" ) ), names )
        if not text:
            continue
        t = tag( text, is_reply=bool( is_reply ) )
        rows.append( (
            str( post[ "id" ] ), str( thread[ "id" ] ), title, is_reply,
            _iso( post[ "creationDate" ][ "epochSecond" ] ), text, post.get( "upvoteCount", 0 ),
            t.kind, t.diamonds, t.gems, now,
        ) )
    return rows


def fetch_item_comments( conn: sqlite3.Connection, wiki: Wiki, title: str ) -> int:
    """Saves the new comments for one item and says how many it saved."""
    prev = conn.execute( "SELECT newest FROM comment_progress WHERE title = ?", ( title, ) ).fetchone()
    stop_before = None
    if prev and prev[ 0 ]:
        stop_before = ( datetime.fromisoformat( prev[ 0 ] ) - timedelta( days=RECHECK_DAYS ) ).isoformat()

    now = datetime.now( timezone.utc ).isoformat( timespec="seconds" )
    newest, total, written = None, 0, 0
    for data in comment_pages( wiki, title ):
        total = data.get( "totalCount", total )
        threads = data.get( "threads" ) or []
        rows = []
        reached_old = False
        for th in threads:
            created = _iso( th[ "creationDate" ][ "epochSecond" ] )
            newest = max( newest or created, created )
            if stop_before and created < stop_before:
                reached_old = True
                break
            rows += rows_from_thread( title, th, now )
        conn.executemany(
            """INSERT INTO comments (post_id, thread_id, title, is_reply, created, text, upvotes,
                                     kind, diamonds, gems, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(post_id) DO UPDATE SET text = excluded.text, upvotes = excluded.upvotes,
                 kind = excluded.kind, diamonds = excluded.diamonds,
                 gems = excluded.gems, fetched_at = excluded.fetched_at""",
            rows,
        )
        written += len( rows )
        if reached_old:
            break

    conn.execute(
        """INSERT INTO comment_progress (title, newest, total_count, fetched_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(title) DO UPDATE SET
             newest = CASE WHEN excluded.newest > COALESCE(comment_progress.newest, '')
                           THEN excluded.newest ELSE comment_progress.newest END,
             total_count = excluded.total_count, fetched_at = excluded.fetched_at""",
        ( title, newest, total, now ),
    )
    conn.commit()
    return written


def connect( path=None ) -> sqlite3.Connection:
    conn = store.connect( path )
    conn.executescript( SCHEMA )
    return conn


def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "--db", help="SQLite file or postgresql:// URL (default: DATABASE_URL, else data/worth.db)" )
    ap.add_argument( "--titles", nargs="+", help="item page titles (default: every item in the database)" )
    ap.add_argument( "--limit", type=int, help="only the first N items" )
    ap.add_argument( "--sample", type=int, help="print N stored comments with their tags and exit" )
    args = ap.parse_args()

    conn = connect( args.db )
    if args.sample:
        for r in conn.execute( "SELECT title, created, kind, diamonds, gems, text FROM comments "
                              "ORDER BY RANDOM() LIMIT ?", ( args.sample, ) ):
            price = ( f"{r[3]:g} dims" if r[ 3 ] is not None else
                     f"{r[4]:g} gems" if r[ 4 ] is not None else "" )
            print( f"[{r[2]:8}] {price:>11}  {r[0]} ({r[1][:10]}): {r[5][:90]!r}" )
        return

    titles = args.titles or [ r[ 0 ] for r in conn.execute( "SELECT title FROM pages ORDER BY title" ) ]
    if not titles:
        print( "No items in the database yet. Run `python3 -m ajworth.fetch` first, or pass --titles." )
        return
    if args.limit:
        titles = titles[ : args.limit ]

    wiki = Wiki()
    for i, title in enumerate( titles, 1 ):
        n = fetch_item_comments( conn, wiki, title )
        print( f"[{i}/{len(titles)}] {title}: {n} posts stored" )

    counts = dict( conn.execute( "SELECT kind, COUNT(*) FROM comments GROUP BY kind" ).fetchall() )
    sold = conn.execute( "SELECT COUNT(*) FROM listings WHERE sold" ).fetchone()[ 0 ]
    print( f"\nDatabase now holds {sum(counts.values())} posts: {counts}; {sold} listings confirmed sold." )


if __name__ == "__main__":
    main()
