"""Label comments by hand, fast. Your labels are what the model learns from!

Usage (after collecting some comments with `python3 -m ajworth.comments`):
    python3 -m ajworth.label            # label until you quit
    python3 -m ajworth.label --stats    # how many of each label you have so far

Each comment shows the rule tagger's guess. Press Enter if it's right, or a key:
    s = sale     d = sold     t = trade     i = iso (looking for)
    q = question o = other    x = skip      ? = show keys     quit = stop
It saves to data/labels.csv after every answer, so stop whenever you want.

It mixes up the kinds of comments it shows you, so you're not stuck labeling
200 "1 dim" listings in a row.
"""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from pathlib import Path

from . import comments

KEYS = { "s": "sale", "d": "sold", "t": "trade", "i": "iso", "q": "question", "o": "other" }
LABELS = list( KEYS.values() )
FIELDS = [ "post_id", "is_reply", "text", "label", "rule_guess" ]


def load_labels( path: Path ) -> dict[ str, dict ]:
    if not path.exists():
        return {}
    with path.open( newline="", encoding="utf-8" ) as f:
        return { row[ "post_id" ]: row for row in csv.DictReader( f ) }


def append_label( path: Path, row: dict ) -> None:
    new = not path.exists()
    path.parent.mkdir( parents=True, exist_ok=True )
    with path.open( "a", newline="", encoding="utf-8" ) as f:
        w = csv.DictWriter( f, fieldnames=FIELDS )
        if new:
            w.writeheader()
        w.writerow( row )


def candidates( conn, done: set[ str ], seed: int | None = None ) -> list[ dict ]:
    """Comments you haven't labeled yet, mixed up so you get a bit of every kind."""
    rows = [ dict( r ) for r in conn.execute(
        "SELECT post_id, is_reply, text, kind FROM comments" ) ]
    rng = random.Random( seed )
    groups: dict[ str, list[ dict ] ] = {}
    for r in rows:
        if r[ "post_id" ] not in done:
            groups.setdefault( r[ "kind" ], [] ).append( r )
    for g in groups.values():
        rng.shuffle( g )
    out = []
    while any( groups.values() ):                     # take turns: one of each kind, then repeat
        for k in sorted( groups ):
            if groups[ k ]:
                out.append( groups[ k ].pop() )
    return out


def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "--db", default="data/worth.db" )
    ap.add_argument( "--out", default="data/labels.csv" )
    ap.add_argument( "--stats", action="store_true" )
    args = ap.parse_args()

    out = Path( args.out )
    done = load_labels( out )
    if args.stats:
        counts = Counter( r[ "label" ] for r in done.values() )
        print( f"{len(done)} labeled: " + ", ".join( f"{k} {counts.get(k, 0)}" for k in LABELS ) )
        return

    conn = comments.connect( args.db )
    todo = candidates( conn, set( done ) )
    if not todo:
        print( "Nothing left to label. Collect more comments with `python3 -m ajworth.comments`." )
        return

    print( f"{len(done)} labeled so far, {len(todo)} to go. Enter = agree with the guess, ? = keys, quit = stop.\n" )
    for n, r in enumerate( todo, len( done ) + 1 ):
        kind = "reply" if r[ "is_reply" ] else "post"
        print( f"#{n} ({kind})  {r['text']}" )
        while True:
            ans = input( f"   guess: {r['kind']}  > " ).strip().lower()
            if ans == "quit":
                print( f"Saved. {n - 1} labeled in total." )
                return
            if ans == "?":
                print( "   " + "  ".join( f"{k}={v}" for k, v in KEYS.items() ) + "  x=skip" )
                continue
            if ans == "x":
                label = None
            elif ans == "":
                label = r[ "kind" ]
            elif ans in KEYS:
                label = KEYS[ ans ]
            else:
                print( "   ? for keys" )
                continue
            break
        if label:
            append_label( out, { "post_id": r[ "post_id" ], "is_reply": r[ "is_reply" ], "text": r[ "text" ],
                               "label": label, "rule_guess": r[ "kind" ] } )
        print()


if __name__ == "__main__":
    main()
