"""The value ladder, built straight from the wiki (no made-up numbers!).

The wiki has "worth counter" pages: RIMs, Clothing Betas, Den Betas, and the four
kinds of spikes. Their tables put a trade value and a diamond price side by side:

    Yellow Short Collar  ->  "3 Decent Long Wrists"  and  "65-70 Diamonds"  and  "Decent"

Every pairing like that becomes an anchor: "3 Decent Long Wrists" is about
65-70 diamonds. Spike pages also give tiers (Bad / Decent / Good / Best), so we
get anchors like "Decent Short Collar" and "Black Short Collar" too.

Then place() can put any worth label on the ladder, even ones built out of
pieces, like "1 Good Short Collar + 1 Bad Short Collar" or "2 Bad Long Collars".

Usage (after `python3 -m ajworth.fetch`):
    python3 -m ajworth.ladder                          # show the ladder, cheapest first
    python3 -m ajworth.ladder --place "3 Bad Long Wrists"
    python3 -m ajworth.ladder --compare "Black Short Collar" "Bad Long Collar"
    python3 -m ajworth.ladder --check                  # which wiki labels it can't place yet

Heads up: the diamond numbers are just how we line things up, using the wiki's
own prices. The chatbot still quotes the wiki's words and decides how to say
it ("close, your call" etc.), it doesn't do math at people.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from dataclasses import dataclass
from pathlib import Path

from . import store
from .parse import table_groups

# Which wiki page is the counter for which unit
COUNTER_PAGES = {
    "Obtainable RIMs": "RIM",
    "Clothing Betas": "Clothing Beta",
    "Den Betas": "Den Beta",
    "Rare Short Spiked Wristband": "Short Wrist",
    "Rare Long Spiked Wristband": "Long Wrist",
    "Rare Short Spiked Collar": "Short Collar",
    "Rare Long Spiked Collar": "Long Collar",
}
SPIKES = { "Short Wrist", "Long Wrist", "Short Collar", "Long Collar" }
QUALITIES = { "bad", "decent", "good", "best" }

DIAMONDS_RE = re.compile( r"(\d[\d,]*)(?:\s*(?:-|–|to)\s*(\d[\d,]*))?\s*diamonds?\b", re.IGNORECASE )
NOT_A_VALUE = re.compile( r"currently in stores|under investigation|unknown|n/a", re.IGNORECASE )
QTY_RE = re.compile( r"^(a few|a couple|\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?\s+(.+)$", re.IGNORECASE )
FUZZY_RE = re.compile( r",?\s*maybe (?:less|more)\s*$|\s*\+\s*(?:an\s+)?add\s*$|\s*\(.*?\)\s*$", re.IGNORECASE )
WORDS_FOR = { "a few": ( 2, 4 ), "a couple": ( 2, 2 ) }


@dataclass
class Placement:
    lo: float              # in diamonds, using the wiki's own prices
    hi: float
    how: str               # how we got there, like "anchor" or "3 x Bad Long Wrist"
    fuzzy: bool = False    # the wiki said "maybe less/more" or "+ add"

    def __add__( self, other: "Placement" ) -> "Placement":
        return Placement( self.lo + other.lo, self.hi + other.hi, f"{self.how} + {other.how}",
                          self.fuzzy or other.fuzzy )


def diamonds( text: str ) -> tuple[ float, float ] | None:
    """'60-65 Diamonds' -> (60, 65), '1 Diamond OR 15,000 Gems' -> (1, 1), else None."""
    m = DIAMONDS_RE.search( text )
    if not m:
        return None
    lo = float( m.group( 1 ).replace( ",", "" ) )
    hi = float( m.group( 2 ).replace( ",", "" ) ) if m.group( 2 ) else lo
    return lo, hi


def norm( label: str ) -> str:
    """Lowercase, single spaces, and plurals made singular so 'Long Wrists' == 'long wrist'."""
    words = re.sub( r"\s+", " ", label.strip().lower() ).split( " " )
    if words and words[ -1 ].endswith( "s" ) and len( words[ -1 ] ) > 3:
        words[ -1 ] = words[ -1 ][ :-1 ]      # wrists -> wrist, rims -> rim, betas -> beta
    return " ".join( words )


class Ladder:
    def __init__( self, anchors: dict[ str, tuple[ float, float ] ] ):
        self.anchors = anchors    # normalized label -> (lo, hi) diamonds

    # ------------------------------------------------------------ building it

    @classmethod
    def from_pages( cls, pages: dict[ str, str ] ) -> "Ladder":
        """Reads every page's tables and collects anchors."""
        seen: dict[ str, list[ tuple[ float, float ] ] ] = {}

        def add( label: str, rng: tuple[ float, float ] ):
            seen.setdefault( norm( label ), [] ).append( rng )

        for title, text in pages.items():
            unit = COUNTER_PAGES.get( title )
            for g in table_groups( text ):
                worth = g.worth_row
                dia_row = next( ( r for r in g.text_rows
                                  if r is not worth and _mostly( r, lambda c: diamonds( c ) is not None ) ), None )
                q_row = next( ( r for r in g.text_rows
                                if _mostly( r, lambda c: c.lower() in QUALITIES ) ), None )
                if dia_row is None:
                    continue
                for i, cell in enumerate( dia_row ):
                    rng = diamonds( cell )
                    if rng is None:
                        continue
                    # the trade value next to a diamond price is an anchor
                    if worth and i < len( worth ) and worth[ i ] and diamonds( worth[ i ] ) is None:
                        add( worth[ i ], rng )
                    if unit is None:
                        continue
                    # every item on a counter page IS one of that counter
                    add( unit, rng )
                    if unit in SPIKES:
                        header = g.headers[ i ] if i < len( g.headers ) else ""
                        if header:
                            add( f"{header} {unit}", rng )            # like "Orange Long Collar"
                        q = q_row[ i ].lower() if q_row and i < len( q_row ) else ""
                        if q in QUALITIES:
                            tier = "Black" if q == "best" else q.title()
                            add( f"{tier} {unit}", rng )              # like "Decent Long Collar"

        # lots of observations per label -> use the middle of the los and of the his
        anchors = { k: ( statistics.median( r[ 0 ] for r in v ), statistics.median( r[ 1 ] for r in v ) )
                    for k, v in seen.items() }
        ladder = cls( anchors )
        ladder._fill_units_from_amounts()
        return ladder

    def _fill_units_from_amounts( self ):
        """If we know "A Few RIMs" is about 1 diamond but not what 1 RIM is,
        work it backwards (a few = 2-4, so 1 RIM is about 0.25-0.5)."""
        for label, ( lo, hi ) in list( self.anchors.items() ):
            m = QTY_RE.match( label )
            if not m:
                continue
            unit = norm( m.group( 3 ) )
            if unit in self.anchors:
                continue
            q_lo, q_hi = _qty( m.group( 1 ), m.group( 2 ) )
            self.anchors[ unit ] = ( lo / q_hi, hi / q_lo )

    # ------------------------------------------------------------ using it

    def place( self, label: str ) -> Placement | None:
        """Puts a worth label on the ladder, or None if we can't (or it isn't a value)."""
        label = label.strip()
        if not label or NOT_A_VALUE.search( label ):
            return None
        fuzzy = bool( FUZZY_RE.search( label ) )
        label = FUZZY_RE.sub( "", label ).strip()

        rng = diamonds( label )
        if rng and DIAMONDS_RE.fullmatch( label.strip() ):
            return Placement( *rng, "diamonds", fuzzy )

        key = norm( label )
        if key in self.anchors:
            return Placement( *self.anchors[ key ], "wiki anchor", fuzzy )

        # "1 Good Short Collar + 1 Bad Short Collar" -> add the pieces up (the wiki's own math)
        if "+" in label:
            parts = [ self.place( p ) for p in label.split( "+" ) ]
            if all( parts ):
                total = parts[ 0 ]
                for p in parts[ 1: ]:
                    total = total + p
                total.fuzzy = total.fuzzy or fuzzy
                return total
            return None

        # "Black Short Collar - Bad Long Collar" -> somewhere between the two
        span = re.split( r"\s+[-–]\s+|\s+to\s+", label )
        if len( span ) == 2 and not span[ 0 ].strip().isdigit():
            # "Decent - Good Long Collar" really means "Decent Long Collar - Good Long Collar"
            if span[ 0 ].strip().lower() in { "bad", "decent", "good", "black" }:
                span[ 0 ] = f"{span[ 0 ].strip()} {' '.join( span[ 1 ].split()[ 1: ] )}"
            a, b = self.place( span[ 0 ] ), self.place( span[ 1 ] )
            if a and b:
                return Placement( min( a.lo, b.lo ), max( a.hi, b.hi ), f"between {a.how} and {b.how}", fuzzy )

        # "3 Bad Long Wrists", "8-9 Den Betas", "A Few Clothing Betas"
        m = QTY_RE.match( label )
        if m:
            unit = self.place( m.group( 3 ) )
            if unit:
                q_lo, q_hi = _qty( m.group( 1 ), m.group( 2 ) )
                return Placement( unit.lo * q_lo, unit.hi * q_hi,
                                  f"{m.group( 1 )}{'-' + m.group( 2 ) if m.group( 2 ) else ''} x {m.group( 3 )}",
                                  fuzzy or unit.fuzzy )
        return None

    def compare( self, a: str, b: str ) -> str:
        """'higher', 'lower' or 'close' (for a vs b), or 'unknown' if either can't be placed."""
        pa, pb = self.place( a ), self.place( b )
        if not pa or not pb:
            return "unknown"
        if pa.lo > pb.hi:
            return "higher"
        if pa.hi < pb.lo:
            return "lower"
        return "close"          # the ranges overlap, so it's really the trader's call

    def tiers( self ) -> list[ tuple[ str, tuple[ float, float ] ] ]:
        """The main rungs (units and their Bad/Decent/Good/Black tiers), cheapest first."""
        names = { norm( u ) for u in COUNTER_PAGES.values() }
        for u in SPIKES:
            names |= { norm( f"{t} {u}" ) for t in ( "Bad", "Decent", "Good", "Black" ) }
        rows = [ ( k, v ) for k, v in self.anchors.items() if k in names ]
        return sorted( rows, key=lambda kv: ( kv[ 1 ][ 0 ], kv[ 1 ][ 1 ] ) )

    def to_json( self ) -> str:
        return json.dumps( { k: list( v ) for k, v in sorted( self.anchors.items() ) }, indent=1 )

    @classmethod
    def from_json( cls, text: str ) -> "Ladder":
        return cls( { k: ( v[ 0 ], v[ 1 ] ) for k, v in json.loads( text ).items() } )

    @classmethod
    def load( cls, conn, path: str | Path = "data/ladder.json" ) -> "Ladder":
        """Uses the saved ladder if there is one (fast), otherwise builds it from the database."""
        p = Path( path )
        if p.exists():
            return cls.from_json( p.read_text() )
        ladder = cls.from_pages( store.all_wikitext( conn ) )
        p.parent.mkdir( parents=True, exist_ok=True )
        p.write_text( ladder.to_json() )
        return ladder


def _mostly( row: list[ str ], test ) -> bool:
    filled = [ c for c in row if c ]
    return bool( filled ) and sum( 1 for c in filled if test( c ) ) * 2 >= len( filled )


def _qty( a: str, b: str | None ) -> tuple[ float, float ]:
    if a.lower() in WORDS_FOR:
        return WORDS_FOR[ a.lower() ]
    return float( a ), float( b ) if b else float( a )


def _fmt( lo: float, hi: float ) -> str:
    f = lambda x: f"{x:g}" if x >= 1 else f"{x:.2g}"
    return f"{f( lo )}" if lo == hi else f"{f( lo )}-{f( hi )}"


def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "--db", help="SQLite file or postgresql:// URL (default: DATABASE_URL, else data/worth.db)" )
    ap.add_argument( "--out", default="data/ladder.json" )
    ap.add_argument( "--place", help="put one worth label on the ladder" )
    ap.add_argument( "--compare", nargs=2, metavar=( "A", "B" ), help="is A higher, lower or close to B?" )
    ap.add_argument( "--check", action="store_true", help="list wiki labels it can't place yet" )
    args = ap.parse_args()

    conn = store.connect( args.db )
    pages = store.all_wikitext( conn )
    missing = [ t for t in COUNTER_PAGES if t not in pages ]
    if missing:
        print( f"Missing counter pages: {', '.join( missing )}. Run `python3 -m ajworth.fetch` (no --limit) first." )
    ladder = Ladder.from_pages( pages )
    Path( args.out ).parent.mkdir( parents=True, exist_ok=True )
    Path( args.out ).write_text( ladder.to_json() )

    if args.place:
        p = ladder.place( args.place )
        print( "can't place that one" if p is None else
               f"{args.place}: ~{_fmt( p.lo, p.hi )} diamonds ({p.how}{', fuzzy' if p.fuzzy else ''})" )
    elif args.compare:
        print( f"{args.compare[ 0 ]} vs {args.compare[ 1 ]}: {ladder.compare( *args.compare )}" )
    elif args.check:
        bad = [ ( lab, n ) for lab, n in store.label_counts( conn ) if ladder.place( lab ) is None
                and not NOT_A_VALUE.search( lab ) ]
        total = sum( n for _, n in store.label_counts( conn ) )
        print( f"{len( bad )} labels can't be placed yet ({sum( n for _, n in bad )} of {total} values):" )
        for lab, n in bad:
            print( f"{n:6}  {lab}" )
    else:
        print( "The ladder, cheapest first (diamonds = the wiki's own prices):\n" )
        for name, ( lo, hi ) in ladder.tiers():
            pretty = name.title().replace( "Rim", "RIM" )
            print( f"  {pretty:<22} {_fmt( lo, hi ):>10}" )
        print( f"\n{len( ladder.anchors )} anchors saved to {args.out}" )


if __name__ == "__main__":
    main()
