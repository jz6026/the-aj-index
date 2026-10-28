"""Builds the ladder from the real counter pages (saved copies) and checks it
lines up with how trading actually works."""

from pathlib import Path

import pytest

from ajworth import store
from ajworth.ladder import COUNTER_PAGES, Ladder, diamonds, norm
from ajworth.parse import parse_page

FIXTURES = Path( __file__ ).parent / "fixtures" / "counters"


@pytest.fixture( scope="module" )
def ladder():
    pages = { t: ( FIXTURES / ( t.lower().replace( " ", "_" ) + ".wikitext" ) ).read_text() for t in COUNTER_PAGES }
    return Ladder.from_pages( pages )


def test_tiers_come_from_the_wiki( ladder ):
    p = ladder.place
    assert ( p( "Bad Short Collar" ).lo, p( "Bad Short Collar" ).hi ) == ( 60, 65 )
    assert ( p( "Black Long Collar" ).lo, p( "Black Long Collar" ).hi ) == ( 300, 320 )
    assert ( p( "Good Long Wrist" ).lo, p( "Good Long Wrist" ).hi ) == ( 30, 35 )


def test_order_matches_how_trading_works( ladder ):
    c = ladder.compare
    assert c( "Black Long Wrist", "Bad Short Collar" ) == "lower"      # wrists are under short collars
    assert c( "Good Long Wrist", "Bad Long Collar" ) == "lower"
    assert c( "Black Short Collar", "Bad Long Collar" ) == "close"     # the wiki even says "Black Short - Bad Long"
    assert c( "Black Long Collar", "Good Long Collar" ) == "higher"
    assert c( "Den Beta", "Clothing Beta" ) == "higher"
    assert c( "Clothing Beta", "RIM" ) == "higher"


def test_labels_built_from_pieces( ladder ):
    p = ladder.place
    assert p( "3 Bad Long Wrists" ) is not None
    assert p( "1 Good Short Collar + 1 Bad Short Collar" ).lo > p( "Good Short Collar" ).lo
    span = p( "Decent - Good Long Collar" )
    assert span.lo == p( "Decent Long Collar" ).lo and span.hi == p( "Good Long Collar" ).hi
    assert p( "1 Black Long Collar, maybe less" ).fuzzy
    assert p( "1 Good Long Collar + add" ).fuzzy
    assert p( "10 Black Long Collars" ).lo == 10 * p( "Black Long Collar" ).lo
    assert p( "1 RIM" ).hi < p( "A Few RIMs" ).hi                     # worked out backwards from "A Few RIMs"


def test_not_values( ladder ):
    assert ladder.place( "Currently in stores" ) is None
    assert ladder.place( "Under Investigation" ) is None
    assert ladder.compare( "Currently in stores", "1 RIM" ) == "unknown"


def test_helpers():
    assert diamonds( "60-65 Diamonds" ) == ( 60, 65 )
    assert diamonds( "1 Diamond OR 15,000 Gems" ) == ( 1, 1 )
    assert diamonds( "A Few RIMs" ) is None
    assert norm( "Long  Wrists" ) == "long wrist"


def test_store_keeps_wikitext_for_rebuilding( tmp_path, db_target ):
    conn = store.connect( db_target )
    text = ( FIXTURES / "rare_short_spiked_collar.wikitext" ).read_text()
    store.save_page( conn, parse_page( "Rare Short Spiked Collar", text ), 1, None, wikitext=text )
    assert store.all_wikitext( conn ) == { "Rare Short Spiked Collar": text }
