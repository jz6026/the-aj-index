"""SQLite (or Postgres, see db.py) storage. Every value ever seen is kept & stamped with the wiki revision
it came from, so value history/trends builds up automatically over time"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .parse import ItemPage

SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    title         TEXT PRIMARY KEY,
    rev_id        INTEGER,          -- the newest wiki version we've read
    rev_timestamp TEXT,             -- when that version was edited
    last_updated  TEXT,             -- the "Last Updated" date on the page
    categories    TEXT,             -- a JSON list
    fetched_at    TEXT,
    wikitext      TEXT              -- the raw page, so we can re-read it later without re-downloading
);

CREATE TABLE IF NOT EXISTS worth_snapshots (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    section       TEXT NOT NULL,
    variant       TEXT NOT NULL,
    worth_raw     TEXT NOT NULL,
    image         TEXT,
    rev_id        INTEGER NOT NULL,
    rev_timestamp TEXT,
    last_updated  TEXT,
    fetched_at    TEXT NOT NULL,
    UNIQUE (title, section, variant, rev_id)
);
CREATE INDEX IF NOT EXISTS idx_snap_item ON worth_snapshots (title, variant);

-- The newest worth for every item + color. This is what the app reads.
CREATE VIEW IF NOT EXISTS current_worth AS
SELECT s.title, s.section, s.variant, s.worth_raw, s.image, s.last_updated
FROM worth_snapshots s
JOIN pages p ON p.title = s.title AND p.rev_id = s.rev_id;
"""


def connect( path: str | Path | None = None ) -> sqlite3.Connection:
    """Opens the database (a SQLite file or a postgresql:// URL, see db.py) and makes
    sure the tables exist. No path = whatever db.default_target() picks."""
    conn = db.connect( path )
    conn.executescript( SCHEMA )
    # databases made before the wikitext column existed get it added here
    if db.dialect( conn ) == "postgres":
        conn.execute( "ALTER TABLE pages ADD COLUMN IF NOT EXISTS wikitext TEXT" )
        conn.commit()
        return conn
    cols = { r[ "name" ] for r in conn.execute( "PRAGMA table_info(pages)" ) }
    if "wikitext" not in cols:
        conn.execute( "ALTER TABLE pages ADD COLUMN wikitext TEXT" )
    return conn


def known_revisions( conn: sqlite3.Connection ) -> dict[ str, int ]:
    return { r[ "title" ]: r[ "rev_id" ] for r in conn.execute( "SELECT title, rev_id FROM pages" ) }


def save_page( conn: sqlite3.Connection, page: ItemPage, rev_id: int, rev_timestamp: str | None,
               wikitext: str | None = None ) -> bool:
    """Saves a page. Returns False (and saves nothing new) if we already have this version."""
    row = conn.execute( "SELECT rev_id, wikitext FROM pages WHERE title = ?", ( page.title, ) ).fetchone()
    if row and row[ "rev_id" ] == rev_id:
        if wikitext and row[ "wikitext" ] is None:   # fill in the raw text for older databases
            conn.execute( "UPDATE pages SET wikitext = ? WHERE title = ?", ( wikitext, page.title ) )
            conn.commit()
        return False

    now = datetime.now( timezone.utc ).isoformat( timespec="seconds" )
    conn.executemany(
        """INSERT OR IGNORE INTO worth_snapshots
           (title, section, variant, worth_raw, image, rev_id, rev_timestamp, last_updated, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [ ( v.item, v.section, v.variant, v.worth_raw, v.image, rev_id, rev_timestamp, page.last_updated, now )
         for v in page.variants ],
    )
    conn.execute(
        """INSERT INTO pages (title, rev_id, rev_timestamp, last_updated, categories, fetched_at, wikitext)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(title) DO UPDATE SET
             rev_id = excluded.rev_id, rev_timestamp = excluded.rev_timestamp,
             last_updated = excluded.last_updated, categories = excluded.categories,
             fetched_at = excluded.fetched_at, wikitext = excluded.wikitext""",
        ( page.title, rev_id, rev_timestamp, page.last_updated, json.dumps( page.categories ), now, wikitext ),
    )
    conn.commit()
    return True


def reparse( conn, parse ) -> int:
    """Re-reads every saved page with the current parser (no downloading) and fixes up
    the values for its newest version. For when parse.py gets smarter, like the Cupid Wings
    fix. Older versions' history stays as it was. Returns how many pages changed."""
    changed = 0
    now = datetime.now( timezone.utc ).isoformat( timespec="seconds" )
    pages = conn.execute( "SELECT title, rev_id, rev_timestamp, wikitext FROM pages "
                          "WHERE wikitext IS NOT NULL" ).fetchall()
    for title, rev_id, rev_ts, text in pages:
        page = parse( title, text )
        new = sorted( ( v.section, v.variant, v.worth_raw, v.image or "" ) for v in page.variants )
        old = sorted( ( r[ 0 ], r[ 1 ], r[ 2 ], r[ 3 ] or "" ) for r in conn.execute(
            "SELECT section, variant, worth_raw, image FROM worth_snapshots WHERE title = ? AND rev_id = ?",
            ( title, rev_id ) ) )
        if new == old:
            continue
        conn.execute( "DELETE FROM worth_snapshots WHERE title = ? AND rev_id = ?", ( title, rev_id ) )
        conn.executemany(
            """INSERT INTO worth_snapshots
               (title, section, variant, worth_raw, image, rev_id, rev_timestamp, last_updated, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [ ( title, v.section, v.variant, v.worth_raw, v.image, rev_id, rev_ts, page.last_updated, now )
              for v in page.variants ],
        )
        changed += 1
    conn.commit()
    return changed


def all_wikitext( conn: sqlite3.Connection ) -> dict[ str, str ]:
    """Every saved page's raw text, by title."""
    return { r[ "title" ]: r[ "wikitext" ] for r in conn.execute(
        "SELECT title, wikitext FROM pages WHERE wikitext IS NOT NULL" ) }


def export_json( conn: sqlite3.Connection, path: str | Path ) -> int:
    """Writes all the current values to one JSON file, so the website and Mac panel
    can look things up super fast without the database."""
    rows = [ dict( r ) for r in conn.execute(
        "SELECT * FROM current_worth ORDER BY title, section, variant" ) ]
    Path( path ).parent.mkdir( parents=True, exist_ok=True )
    Path( path ).write_text( json.dumps( rows, ensure_ascii=False, indent=1 ) )
    return len( rows )


def label_counts( conn: sqlite3.Connection ) -> list[ tuple[ str, int ] ]:
    """Every worth label the wiki uses ("A Few RIMs" etc.), most common first.
    Handy for seeing the wiki's whole ladder of values."""
    return [ ( r[ 0 ], r[ 1 ] ) for r in conn.execute(
        "SELECT worth_raw, COUNT(*) FROM current_worth GROUP BY worth_raw ORDER BY 2 DESC, 1" ) ]
