"""Name matching + trade checks, using the saved wiki pages (Beard + the counter pages)."""

from pathlib import Path

import pytest

from ajworth.ladder import COUNTER_PAGES, Ladder
from ajworth.match import Entry, Matcher, expand_slang, wiki_aliases, words
from ajworth.parse import parse_page
from ajworth.trade import check, render, split_sides

FIXTURES = Path( __file__ ).parent / "fixtures"


@pytest.fixture( scope="module" )
def world():
    pages = { t: ( FIXTURES / "counters" / ( t.lower().replace( " ", "_" ) + ".wikitext" ) ).read_text()
              for t in COUNTER_PAGES }
    pages[ "Beard" ] = ( FIXTURES / "beard.wikitext" ).read_text()
    entries = [ Entry( t, v.variant, v.section, v.worth_raw ) for t, txt in pages.items()
                for v in parse_page( t, txt ).variants ]
    aliases = { " ".join( words( a ) ): ( t, v ) for t, txt in pages.items() for a, v in wiki_aliases( t, txt ) }
    return Matcher( entries, aliases ), Ladder.from_pages( pages )


# ------------------------------------------------------------ matching names

def test_slang():
    assert expand_slang( "blk long" ) == "black long collar"
    assert expand_slang( "long wrist" ) == "long wrist"          # already a full name, leave it
    assert expand_slang( "lb beard" ) == "light brown beard"


@pytest.mark.parametrize( "typed, expected", [
    ( "blk long", "Rare Long Spiked Collar - Black" ),
    ( "solid", "Rare Long Spiked Collar - Black" ),            # wiki nickname
    ( "pure", "Rare Long Spiked Collar - Black" ),
    ( "lb beard", "Beard - Light Brown" ),
    ( "ly beard", "Beard - Leap Year" ),
    ( "rim beard", "Beard - Rare Item Monday" ),
    ( "pnk beard", "Beard - Pink" ),                            # typo
    ( "blk lw", "Rare Long Spiked Wristband - Black" ),
    ( "purple short", "Rare Short Spiked Collar - Purple" ),
] )
def test_finds_items( world, typed, expected ):
    m = world[ 0 ].find( typed )
    assert m.ok and m.best.name == expected


def test_asks_which_color_only_when_values_differ( world ):
    m = world[ 0 ].find( "beard" )
    assert m.needs_color                    # the Luminous one is worth more, so it has to ask
    assert world[ 0 ].find( "xyzzy" ).best is None


def test_wiki_nicknames():
    text = "The Black variant is commonly referred to as 'Black Long,' 'Solid,' or 'Pure'."
    assert ( "Solid", "Black" ) in wiki_aliases( "Rare Long Spiked Collar", text )


# ------------------------------------------------------------ reading trades

@pytest.mark.parametrize( "text, give, get, assumed", [
    ( "my leap year beard for their pink beard?", "leap year beard", "pink beard", False ),
    ( "ok what about their ly beard for my pink + lb beard", "pink + lb beard", "ly beard", False ),
    ( "pink beard for 3 dbs", "pink beard", "3 dbs", True ),
] )
def test_split_sides( text, give, get, assumed ):
    assert split_sides( text ) == ( give, get, assumed )


# ------------------------------------------------------------ verdicts (her mockup trades!)

def test_mockup_trade_one_is_over( world ):
    r = check( "my leap year beard for their pink beard", *world )
    assert r.verdict == "way_over"
    assert [ l.wiki for l in r.give ] == [ "Good Short Collar" ]   # quoted word for word
    assert [ l.wiki for l in r.get ] == [ "A Few RIMs" ]


def test_mockup_trade_two_is_worth_it( world ):
    r = check( "their leap year beard for my pink + light brown beard", *world )
    assert r.verdict == "good"
    assert len( r.give ) == 2


def test_counters_and_fuzzy( world ):
    r = check( "my blk long for 2 bad longs", *world )
    assert r.verdict == "close"
    assert any( "loose" in n for n in r.notes )        # Black Long is "1 Good Long Collar + add"


def test_small_deals_stay_calm( world ):
    r = check( "my pink beard for their rim beard", *world )
    assert r.verdict == "over"
    assert any( "small deal" in n for n in r.notes )


def test_needs_more_info( world ):
    r = check( "beard for 3 dbs", *world )
    assert r.verdict == "unsure"
    assert any( "Which one" in n for n in r.notes )
    assert "double-check before you accept" in render( r )
