"""Grabs every item page from the AJ Item Worth Wiki using its API.

Usage (from the project folder):
    python3 -m ajworth.fetch                 # full refresh
    python3 -m ajworth.fetch --limit 20      # quick test on 20 pages
    python3 -m ajworth.fetch --labels        # list every worth label in the database

It tries to be a good guest: says who it is, waits between requests, backs off
when the wiki is busy, and only re-reads pages that actually changed.
"""

from __future__ import annotations

import argparse
import time
from typing import Iterator

import requests

from . import store
from .parse import parse_page

API = "https://aj-item-worth.fandom.com/api.php"
CATEGORY = "Category:Items"
BATCH = 50          # the most pages the API lets us ask for at once
PAUSE = 1.0         # seconds to wait between requests (be nice to the wiki)
USER_AGENT = "AJWorthLookup/0.1 (student project; personal use)"


class Wiki:
    def __init__( self, session: requests.Session | None = None, pause: float = PAUSE ):
        self.s = session or requests.Session()
        self.s.headers[ "User-Agent" ] = USER_AGENT
        self.pause = pause

    def _get( self, **params ) -> dict:
        params |= { "format": "json", "formatversion": 2, "maxlag": 5 }
        return self.get_json( API, params )

    def get_json( self, url: str, params: dict | None = None ) -> dict:
        """Gets JSON from a URL. If the wiki says slow down, waits and tries again."""
        for attempt in range( 5 ):
            r = self.s.get( url, params=params, timeout=30 )
            if r.status_code == 429 or "maxlag" in r.text[ :200 ]:
                time.sleep( int( r.headers.get( "Retry-After", 5 ) ) * ( attempt + 1 ) )
                continue
            r.raise_for_status()
            time.sleep( self.pause )
            return r.json()
        raise RuntimeError( "Wiki kept asking us to slow down; try again later." )

    def item_titles( self ) -> Iterator[ str ]:
        """Every page in Category:Items (keeps going until there are no more pages)."""
        cont: dict = {}
        while True:
            data = self._get( action="query", list="categorymembers", cmtitle=CATEGORY,
                             cmnamespace=0, cmlimit=500, **cont )
            for m in data[ "query" ][ "categorymembers" ]:
                yield m[ "title" ]
            if "continue" not in data:
                return
            cont = data[ "continue" ]

    def pages( self, titles: list[ str ] ) -> Iterator[ tuple[ str, int, str, str ] ]:
        """Gives (title, rev_id, rev_timestamp, wikitext) for each title, 50 at a time."""
        for i in range( 0, len( titles ), BATCH ):
            data = self._get( action="query", prop="revisions", titles="|".join( titles[ i:i + BATCH ] ),
                             rvprop="ids|timestamp|content", rvslots="main" )
            for p in data[ "query" ][ "pages" ]:
                if p.get( "missing" ) or not p.get( "revisions" ):
                    continue
                rev = p[ "revisions" ][ 0 ]
                yield p[ "title" ], rev[ "revid" ], rev[ "timestamp" ], rev[ "slots" ][ "main" ][ "content" ]


def refresh( conn, wiki: Wiki, limit: int | None = None, log=print ) -> dict:
    titles = list( wiki.item_titles() )
    if limit:
        titles = titles[ :limit ]
    log( f"{len(titles)} item pages listed" )

    stats = { "pages": 0, "changed": 0, "variants": 0, "no_table": [] }
    for title, rev_id, ts, text in wiki.pages( titles ):
        page = parse_page( title, text )
        stats[ "pages" ] += 1
        if not page.variants:
            stats[ "no_table" ].append( title )
        if store.save_page( conn, page, rev_id, ts, wikitext=text ):
            stats[ "changed" ] += 1
            stats[ "variants" ] += len( page.variants )
        if stats[ "pages" ] % 100 == 0:
            log( f"  ...{stats['pages']} pages" )
    return stats


def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "--db", default="data/worth.db" )
    ap.add_argument( "--json", default="data/items.json", help="lookup cache to write" )
    ap.add_argument( "--limit", type=int, help="only fetch the first N pages (for testing)" )
    ap.add_argument( "--labels", action="store_true", help="print worth labels and exit" )
    args = ap.parse_args()

    conn = store.connect( args.db )
    if args.labels:
        for label, n in store.label_counts( conn ):
            print( f"{n:6}  {label}" )
        return

    stats = refresh( conn, Wiki(), limit=args.limit )
    n = store.export_json( conn, args.json )
    print( f"\nDone: {stats['pages']} pages read, {stats['changed']} new or changed, "
          f"{stats['variants']} variant values stored." )
    print( f"{n} current values written to {args.json}" )
    if stats[ "no_table" ]:
        sample = ", ".join( stats[ "no_table" ][ :10 ] )
        print( f"{len(stats['no_table'])} pages had no worth table (e.g. {sample})" )


if __name__ == "__main__":
    main()
