"""Turns what people actually type ("blk long", "lb beard", "rim beard") into wiki items.

Three layers, in order:
  1. SLANG: short forms players use. This list is mine to grow! If something
     gets matched wrong, adding a line here is usually the fix.
  2. Wiki nicknames: lines like "commonly referred to as 'Black Long,' 'Solid,'
     or 'Pure'" get pulled straight off the item pages.
  3. Fuzzy word matching: every word you type has to show up in the item's
     name or color (small typos are ok), and the closest fit wins.

If a name fits a few colors that are worth DIFFERENT things on the wiki,
the matcher says so instead of guessing, so the chatbot can ask "which color?".

Usage (after `python3 -m ajworth.fetch`):
    python3 -m ajworth.match "blk long"
    python3 -m ajworth.match "lb beard"
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import re
from dataclasses import dataclass, field

from . import store

# What players type -> what the wiki calls it. Keys are matched as whole words.
SLANG = {
    "blk": "black",
    "bl": "black",
    "lb": "light brown",
    "ly": "leap year",
    "rim": "rare item monday",
    "lw": "long wrist",
    "sw": "short wrist",
    "lc": "long collar",
    "sc": "short collar",
    "longs": "long collar",
    "long": "long collar",
    "shorts": "short collar",
    "short": "short collar",
    "spike": "",
    "spiked": "",
    "spikes": "",
    "cb": "clothing beta",
    "cbs": "clothing beta",
    "db": "den beta",
    "dbs": "den beta",
    "nm": "non member",
    "lum": "luminous",
}
# words that don't help find an item
STOP = { "the", "a", "an", "my", "their", "your", "his", "her", "of", "one", "rare", "s" }

ALIAS_SENTENCE = re.compile( r"[^.\n]*(?:referred to as|commonly known as|also known as|more commonly known as)[^.\n]*",
                             re.IGNORECASE )
QUOTED = re.compile( r"'''+([^']+?)'''+|''([^']+?)''|\"([^\"]+?)\"|'([^']+?)'" )
VARIANT_IN = re.compile( r"\bthe (\w[\w ]*?) variant\b", re.IGNORECASE )


def words( text: str ) -> list[ str ]:
    """Lowercase words, plurals trimmed, 'wristband' == 'wrist', junk words dropped."""
    out = []
    for w in re.findall( r"[a-z0-9]+", text.lower() ):
        if w in ( "wristband", "wristbands", "wrists" ):
            w = "wrist"
        elif len( w ) > 3 and w.endswith( "s" ) and not w.endswith( "ss" ):
            w = w[ :-1 ]
        if w not in STOP:
            out.append( w )
    return out


def expand_slang( text: str ) -> str:
    """'blk long' -> 'black long collar'. Only whole words get swapped."""
    pieces = re.findall( r"[A-Za-z0-9]+|[^A-Za-z0-9]+", text )
    out = []
    for i, p in enumerate( pieces ):
        low = p.lower()
        # "long wrist" / "short wrist" are already full names, so don't turn "long" into "long collar" there
        nxt = "".join( pieces[ i + 1: i + 3 ] ).strip().lower()
        if low in ( "long", "short", "longs", "shorts" ) and nxt.startswith( ( "wrist", "collar", "spike" ) ):
            out.append( low.rstrip( "s" ) )
        elif low in SLANG:
            out.append( SLANG[ low ] )
        else:
            out.append( p )
    return "".join( out )


@dataclass
class Entry:
    title: str
    variant: str
    section: str
    worth_raw: str
    words: set[ str ] = field( default_factory=set )       # title + color + section words
    base: set[ str ] = field( default_factory=set )        # just title + color

    @property
    def name( self ) -> str:
        name = f"{self.title} - {self.variant}" if self.variant else self.title
        # pages with several tables ("Glossy Cupid Wings" vs "Non-Glossy Cupid Wings") need the
        # section in the name, or "which one?" would list two identical names
        if self.section and self.section.lower() not in ( "other variants", "variants" ):
            name += f" ({self.section})"
        return name


@dataclass
class Match:
    query: str
    best: Entry | None
    options: list[ Entry ]        # everything that fit equally well
    needs_color: bool             # True if those options are worth different things

    @property
    def ok( self ) -> bool:
        return self.best is not None and not self.needs_color


def wiki_aliases( title: str, wikitext: str ) -> list[ tuple[ str, str | None ] ]:
    """('Solid', 'Black') style pairs from "commonly referred to as" lines. Variant is None if it's the whole item."""
    found = []
    for sentence in ALIAS_SENTENCE.findall( wikitext ):
        v = VARIANT_IN.search( sentence )
        variant = v.group( 1 ).strip() if v else None
        after = re.split( r"referred to as|known as", sentence, maxsplit=1, flags=re.IGNORECASE )[ -1 ]
        for groups in QUOTED.findall( after ):
            alias = next( g for g in groups if g ).strip( " ,.'\"" )
            if alias and alias.lower() != title.lower():
                found.append( ( alias, variant ) )
    return found


class Matcher:
    def __init__( self, entries: list[ Entry ], aliases: dict[ str, tuple[ str, str | None ] ] | None = None ):
        self.entries = entries
        self.aliases = aliases or {}          # normalized alias -> ( title, variant or None )
        for e in entries:
            e.base = set( words( f"{e.title} {e.variant.replace( '/', ' ' )}" ) )
            # the section's words can be typed too ("glossy black cupid wings"), but they
            # don't count as leftovers when ranking, so plain "beard" still sees every color
            e.words = e.base | set( words( e.section.replace( '/', ' ' ) ) )
        self.vocab = sorted( { w for e in entries for w in e.words } )

    @classmethod
    def from_db( cls, conn ) -> "Matcher":
        rows = conn.execute( "SELECT title, variant, section, worth_raw FROM current_worth" ).fetchall()
        entries = [ Entry( r[ "title" ], r[ "variant" ], r[ "section" ], r[ "worth_raw" ] ) for r in rows ]
        aliases = {}
        for title, text in store.all_wikitext( conn ).items():
            for alias, variant in wiki_aliases( title, text ):
                aliases[ " ".join( words( alias ) ) ] = ( title, variant )
        return cls( entries, aliases )

    def _spellings( self, w: str ) -> list[ str ]:
        """The word itself if we know it, else up to 3 close spellings ('pnk' -> pink, punk...)."""
        if w in self.vocab or w.isdigit():
            return [ w ]
        if len( w ) < 3:
            return []
        # 0.8 = "pnk" -> pink is ok, but "solid" -> old is too much of a stretch
        return difflib.get_close_matches( w, self.vocab, n=3, cutoff=0.8 )

    def find( self, query: str ) -> Match:
        # wiki nicknames first ("solid" -> Rare Long Spiked Collar, Black), then slang
        q = None
        for attempt in ( query, expand_slang( query ) ):
            key = " ".join( words( attempt ) )
            if key in self.aliases:
                title, variant = self.aliases[ key ]
                q = words( f"{title} {variant or ''}" )
                break
        if q is None:
            q = words( expand_slang( query ) )

        options = [ self._spellings( w ) for w in q ]
        if not q or not all( options ):
            return Match( query, None, [], False )
        # try the likeliest spelling combos until one actually fits an item
        fits, need = [], set()
        for combo in itertools.islice( itertools.product( *options ), 27 ):
            need = set( combo )
            fits = [ e for e in self.entries if need <= e.words ]
            if fits:
                break
        if not fits:
            return Match( query, None, [], False )
        # fewest leftover words = closest fit ("pink beard" beats "pink beard hat")
        fits.sort( key=lambda e: ( len( e.base - need ), len( e.title ) ) )
        best_extra = len( fits[ 0 ].base - need )
        top = [ e for e in fits if len( e.base - need ) == best_extra ]
        # typed a section word ("glossy")? then the closest section wins, so
        # "glossy" picks Glossy Cupid Wings over Non-Glossy Cupid Wings
        if any( need - e.base for e in top ):
            closest = min( len( e.words - need ) for e in top )
            top = [ e for e in top if len( e.words - need ) == closest ]

        # same item title for all of them? then it's just "which color", and if
        # every color is worth the same on the wiki we don't even need to ask
        values = { e.worth_raw for e in top }
        return Match( query, top[ 0 ], top, needs_color=len( values ) > 1 )


def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "query", nargs="+" )
    ap.add_argument( "--db", help="SQLite file or postgresql:// URL (default: DATABASE_URL, else data/worth.db)" )
    args = ap.parse_args()

    m = Matcher.from_db( store.connect( args.db ) ).find( " ".join( args.query ) )
    if m.best is None:
        print( "couldn't find that one (try another name, or add it to SLANG in match.py)" )
    elif m.needs_color:
        print( f"which one? these are worth different things:" )
        for e in m.options[ :10 ]:
            print( f"  {e.name:<45} \"{e.worth_raw}\"" )
    else:
        print( f"{m.best.name}  ->  \"{m.best.worth_raw}\"" )
        if len( m.options ) > 1:
            print( f"  (fits {len( m.options )} colors, all worth the same on the wiki)" )


if __name__ == "__main__":
    main()
