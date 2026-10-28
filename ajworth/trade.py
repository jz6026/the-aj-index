"""Checks a trade: finds both sides, quotes the wiki, and gives a short verdict.

This is the brain of the chatbot. The AI part later just turns this into a
friendly reply; every value it says comes from here (so it can't make stuff up).

Usage (after `python3 -m ajworth.fetch`):
    python3 -m ajworth.trade "my leap year beard for their pink beard"
    python3 -m ajworth.trade "their ly beard for my pink beard + lb beard"
    python3 -m ajworth.trade "my blk long for 2 bad longs" --json

How it reads a trade:
  "my X for their Y"    -> you give X, you get Y
  "their X for my Y"    -> you get X, you give Y
  "X for Y"             -> assumes you give X (and says so)
  Items can be joined with +, commas or "and", and can have amounts ("2 bad longs").
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field, asdict

from . import store
from .ladder import Ladder, Placement, diamonds, DIAMONDS_RE
from .match import Matcher, expand_slang

THEIRS = r"(?:their|theirs|your|yours|ur|his|her|the other person'?s)"
MINE = r"(?:my|mine|me)"
FILLER = re.compile( r"^(?:\s*(?:ok(?:ay)?|so|hey|um+|what about|how about|is|would|should i|can i|trade|trading|"
                     r"i'?m|i am|giving|offering)\b[\s,]*)+", re.IGNORECASE )
QTY = re.compile( r"^(\d+(?:\.\d+)?|a few|a couple|two|three|four|five)\s+(.+)$", re.IGNORECASE )
WORD_NUMS = { "two": 2, "three": 3, "four": 4, "five": 5, "a couple": 2 }

VERDICTS = {
    "good": "Trade is worth it",
    "close": "Close, your call",
    "over": "Over. You'd be overpaying",
    "way_over": "Way over. You'd be overpaying a lot",
    "unsure": "Can't call this one yet",
}
FOOTER = "AJ Item Worth Wiki · double-check before you accept"
SMALL_DEAL = 2          # diamonds. if both sides are under this, it's not a big deal either way


@dataclass
class Line:
    text: str                          # what the person typed for this item
    name: str | None = None            # the wiki item, like "Beard - Pink"
    wiki: str | None = None            # the wiki value, word for word
    qty: float = 1
    lo: float | None = None            # placement on the ladder (diamonds), if we have one
    hi: float | None = None
    fuzzy: bool = False
    status: str = "ok"                 # ok | ask (which color?) | no_value | unknown
    options: list[ str ] = field( default_factory=list )


@dataclass
class Result:
    give: list[ Line ]
    get: list[ Line ]
    verdict: str
    message: str
    notes: list[ str ]
    assumed_sides: bool

    def to_dict( self ) -> dict:
        return asdict( self )


# ------------------------------------------------------------ reading the trade

def split_sides( text: str ) -> tuple[ str, str, bool ]:
    """Returns ( give, get, assumed ). assumed=True when we had to guess who gives what."""
    t = FILLER.sub( "", text.strip().rstrip( "?!. " ) )
    t = re.sub( r"\s+(?:fair|worth it|good|ok)\s*$", "", t, flags=re.IGNORECASE )
    m = re.match( rf"^{MINE}\s+(.+?)\s+for\s+{THEIRS}\s+(.+)$", t, re.IGNORECASE )
    if m:
        return m.group( 1 ), m.group( 2 ), False
    m = re.match( rf"^{THEIRS}\s+(.+?)\s+for\s+{MINE}\s+(.+)$", t, re.IGNORECASE )
    if m:
        return m.group( 2 ), m.group( 1 ), False
    m = re.match( rf"^{MINE}\s+(.+?)\s+for\s+(.+)$", t, re.IGNORECASE )
    if m:
        return m.group( 1 ), m.group( 2 ), False
    m = re.match( r"^(.+?)\s+for\s+(.+)$", t, re.IGNORECASE )
    if m:
        return m.group( 1 ), m.group( 2 ), True
    return t, "", True


def split_items( side: str, matcher: Matcher ) -> list[ str ]:
    """'pink beard + lb beard, worn' -> 3 items. "and" only splits if both halves are real items
    (so "black and white beard" stays one thing)."""
    side = re.sub( rf"^\s*(?:{MINE}|{THEIRS})\s+", "", side, flags=re.IGNORECASE )
    parts = [ p.strip() for p in re.split( r"\s*(?:\+|,|&amp;|\bplus\b)\s*", side ) if p.strip() ]
    out = []
    for p in parts:
        halves = re.split( r"\s+and\s+", p )
        if len( halves ) == 2 and all( matcher.find( _strip_qty( h )[ 1 ] ).best for h in halves ):
            out += halves
        else:
            out.append( p )
    return [ re.sub( rf"^\s*(?:{MINE}|{THEIRS})\s+", "", o, flags=re.IGNORECASE ) for o in out ]


def _strip_qty( text: str ) -> tuple[ float, str ]:
    m = QTY.match( text.strip() )
    if not m:
        return 1, text.strip()
    n = m.group( 1 ).lower()
    if n == "a few":
        return 1, text.strip()                # "a few cbs" is a ladder phrase, keep it whole
    return float( WORD_NUMS.get( n, n ) ), m.group( 2 ).strip()


# ------------------------------------------------------------ looking things up

def resolve( text: str, matcher: Matcher, ladder: Ladder ) -> Line:
    qty, name = _strip_qty( text )
    line = Line( text=text, qty=qty )

    # plain diamonds ("50 dims") count as a side too
    d = diamonds( re.sub( r"\bdims?\b", "diamonds", text, flags=re.IGNORECASE ) )
    if d and not matcher.find( name ).best:
        line.name, line.wiki, line.qty = "Diamonds", text, 1
        line.lo, line.hi = d
        return line

    m = matcher.find( name )
    if m.best and not m.needs_color:
        line.name, line.wiki = m.best.name, m.best.worth_raw
        p = ladder.place( m.best.worth_raw )
        if p is None:
            line.status = "no_value"           # "Currently in stores", "Under Investigation", etc.
        else:
            line.lo, line.hi, line.fuzzy = p.lo * qty, p.hi * qty, p.fuzzy
        return line

    # not an item (or not sure which color)? maybe it's a counter like "2 bad longs" or "a few cbs"
    p = ladder.place( expand_slang( text ) )
    if p is not None:
        line.name = expand_slang( text ).strip().title()
        line.wiki = None                       # it IS a wiki unit, no item value to quote
        line.lo, line.hi, line.fuzzy, line.qty = p.lo, p.hi, p.fuzzy, 1
        return line

    if m.best and m.needs_color:
        line.status = "ask"
        line.options = [ f'{e.name} ("{e.worth_raw}")' for e in m.options[ :6 ] ]
    else:
        line.status = "unknown"
    return line


def _total( lines: list[ Line ] ) -> Placement | None:
    if not lines or any( l.lo is None for l in lines ):
        return None
    return Placement( sum( l.lo for l in lines ), sum( l.hi for l in lines ), "side",
                      any( l.fuzzy for l in lines ) )


def _is_diamond_only( line: Line ) -> bool:
    return line.wiki is not None and bool( DIAMONDS_RE.fullmatch( line.wiki.strip() ) )


# ------------------------------------------------------------ the verdict

def check( text: str, matcher: Matcher, ladder: Ladder ) -> Result:
    give_txt, get_txt, assumed = split_sides( text )
    give = [ resolve( t, matcher, ladder ) for t in split_items( give_txt, matcher ) ]
    get = [ resolve( t, matcher, ladder ) for t in split_items( get_txt, matcher ) ] if get_txt else []
    notes: list[ str ] = []

    if assumed and get:
        notes.append( "I assumed you're the one giving the first part. Say \"my ___ for their ___\" if not." )
    for l in give + get:
        if l.status == "ask":
            notes.append( f"Which one is \"{l.text}\"? {', '.join( l.options[ :4 ] )}" )
        elif l.status == "unknown":
            notes.append( f"Couldn't find \"{l.text}\" on the wiki." )
        elif l.status == "no_value":
            notes.append( f"The wiki doesn't give {l.name} a trade value (\"{l.wiki}\")." )

    g, t = _total( give ), _total( get )
    if not get:
        verdict = "unsure"
        notes.append( "What are you getting for it?" )
    elif g is None or t is None:
        verdict = "unsure"
    elif t.lo > g.hi:
        verdict = "good"
    elif g.lo > t.hi:
        verdict = "way_over" if ( g.lo + g.hi ) > 2 * ( t.lo + t.hi ) else "over"
    else:
        verdict = "close"

    # both sides are worth about a diamond or two: don't freak anyone out over it
    if g and t and max( g.hi, t.hi ) <= SMALL_DEAL and verdict in ( "over", "way_over" ):
        verdict = "over"
        notes.append( "Both sides are low value, so it's a small deal either way." )

    if g and t and ( g.fuzzy or t.fuzzy ):
        notes.append( "The wiki says \"maybe more/less\" or \"+ add\" for something here, so it's a bit loose." )
    # lots of little things for one big thing: easy to lose value, hard to trade back up
    if len( give ) == 1 and sum( l.qty for l in get ) >= 3 and verdict in ( "close", "good" ):
        notes.append( "Heads up: lots of small items for one rare one can be hard to trade back up." )
    # diamond-shop prices vs RIM swaps are different kinds of deals
    sides = [ give, get ]
    if any( all( _is_diamond_only( l ) for l in s ) for s in sides ) and \
       any( any( l.wiki and not _is_diamond_only( l ) for l in s ) for s in sides ):
        notes.append( "One side is usually bought with diamonds and the other is usually traded, "
                      "so compare with that in mind." )

    return Result( give, get, verdict, VERDICTS[ verdict ], notes, assumed )


def render( r: Result ) -> str:
    def side( title: str, lines: list[ Line ] ) -> list[ str ]:
        out = [ title ]
        for l in lines:
            label = l.name or l.text
            if l.qty != 1:
                label = f"{l.qty:g} x {label}"
            value = f"\"{l.wiki}\"" if l.wiki else ( "wiki counter" if l.status == "ok" else "?" )
            out.append( f"  {label:<40} {value}" )
        return out

    lines = side( "You are trading:", r.give ) + side( "You are getting:", r.get )
    lines += [ "", f"-> {r.message}" ] + [ f"   {n}" for n in r.notes ] + [ "", FOOTER ]
    return "\n".join( lines )


def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "trade", nargs="+" )
    ap.add_argument( "--db", default="data/worth.db" )
    ap.add_argument( "--json", action="store_true", help="print the result as JSON (for the website)" )
    args = ap.parse_args()

    conn = store.connect( args.db )
    result = check( " ".join( args.trade ), Matcher.from_db( conn ), Ladder.load( conn ) )
    print( json.dumps( result.to_dict(), indent=1 ) if args.json else render( result ) )


if __name__ == "__main__":
    main()
