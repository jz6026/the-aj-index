"""Comment fetching, username scrubbing and tagging. All names here are made up"""

import json

import pytest

from ajworth import comments
from ajworth.fetch import Wiki
from ajworth.tagger import tag, price


def doc( text: str ) -> str:
    """Makes a fake comment the way Fandom stores them, one paragraph per line."""
    return json.dumps( { "type": "doc", "content": [
        { "type": "paragraph", "content": [ { "type": "text", "text": line } ] } for line in text.split( "\n" ) ] } )


def post( pid, epoch, text, author ):
    return { "id": pid, "creationDate": { "epochSecond": epoch }, "jsonModel": doc( text ),
            "upvoteCount": 0, "createdBy": { "name": author } }


def thread( tid, epoch, text, author, replies=() ):
    return { "id": tid, "creationDate": { "epochSecond": epoch },
            "firstPost": post( f"{tid}-0", epoch, text, author ),
            "posts": [ post( f"{tid}-{i + 1}", epoch + 60, t, a ) for i, ( t, a ) in enumerate( replies ) ] }


# ------------------------------------------------------------ scrubbing

@pytest.mark.parametrize( "raw, author, expected", [
    ( "Yellow for 1 dim - Moonpaw88", "Moonpaw88", "Yellow for 1 dim [user]" ),
    ( "Pink for 1 dim at fuzzyfox", "x", "Pink for 1 dim [user]" ),
    ( "Orange - 1 dim\n@ fuzzyfox", "x", "Orange - 1 dim\n@[user]" ),
    ( "1 dim my shop User: fuzzyfox", "x", "1 dim my shop User: [user]" ),
    ( "Deal. my user is fuzzyfox", "x", "Deal. my user: [user]" ),
    ( "Lf pink! jag StarryWolf22", "x", "Lf pink! jag [user]" ),
    ( "I got brown in my shop (fuzzyfox)", "x", "I got brown in my shop [user]" ),
    ( "Silver 4 dims\nExtraFishy", "x", "Silver 4 dims\n[user]" ),
] )
def test_scrub_names( raw, author, expected ):
    assert comments.scrub_names( raw, { author } ) == expected


@pytest.mark.parametrize( "keep", [
    "Selling for 1 dim in my shop",
    "LF orange! will buy, jag me",
    "Great!",
    "Ok",
    "Brown beard (sold)",
] )
def test_scrub_leaves_normal_text_alone( keep ):
    assert comments.scrub_names( keep, { "Moonpaw88" } ) == keep


# ------------------------------------------------------------ tagging

@pytest.mark.parametrize( "text, is_reply, kind, dims, gems", [
    ( "Yellow for 1 dim", False, "sale", 1, None ),
    ( "Rare leap year beard for 80 dims", False, "sale", 80, None ),
    ( "Luminous 5-10 diamonds", False, "sale", 7.5, None ),
    ( "Yellow for 12.5k gems", False, "sale", None, 12500 ),
    ( "Desperately iso light brown !!!", False, "iso", None, None ),
    ( "Sold :)", True, "sold", None, None ),
    ( "Traded, sorry!", True, "sold", None, None ),
    ( "My orange for a cb", False, "trade", None, None ),
    ( "I hv pink ft! any offers?", False, "trade", None, None ),
    ( "what is the pink one worth?", False, "question", None, None ),
    ( "I remember when orange was rare", False, "other", None, None ),
] )
def test_tag( text, is_reply, kind, dims, gems ):
    t = tag( text, is_reply )
    assert ( t.kind, t.diamonds, t.gems ) == ( kind, dims, gems )


def test_price_parsing():
    assert price( "2 diamonds each", "diamonds" ) == 2
    assert price( "15k gems", "gems" ) == 15000
    assert price( "no price here", "diamonds" ) is None


# ------------------------------------------------------------ fetching + storage

class FakeCommentsSession:
    """Pretends to be Fandom's comments API: newest first, 2 threads per page."""

    def __init__( self, threads ):
        self.threads = sorted( threads, key=lambda t: -t[ "creationDate" ][ "epochSecond" ] )
        self.headers, self.requests = {}, 0

    def get( self, url, params, timeout ):
        self.requests += 1
        page = int( params[ "page" ] )
        chunk = self.threads[ page * 2: page * 2 + 2 ]
        links = { "next": "..." } if page * 2 + 2 < len( self.threads ) else {}

        class R:
            status_code, headers = 200, {}
            text = "{}"
            def json( self_inner ): return { "threads": chunk, "links": links, "totalCount": len( self.threads ) }
            def raise_for_status( self_inner ): pass
        return R()


DAY = 86400
T0 = 1_790_000_000   # just some date in 2026


def test_fetch_stores_scrubbed_tagged_and_links_sold_replies( tmp_path ):
    conn = comments.connect( tmp_path / "w.db" )
    data = [
        thread( "a", T0, "Orange - 1 dim @ fuzzyfox", "fuzzyfox", replies=[ ( "Sold!!", "Moonpaw88" ) ] ),
        thread( "b", T0 - DAY, "Pink for 1 dim - Moonpaw88", "Moonpaw88" ),
        thread( "c", T0 - 2 * DAY, "Lf light brown", "StarryWolf22" ),
    ]
    s = FakeCommentsSession( data )
    n = comments.fetch_item_comments( conn, Wiki( s, pause=0 ), "Beard" )
    assert n == 4

    texts = " ".join( r[ 0 ] for r in conn.execute( "SELECT text FROM comments" ) )
    for name in ( "fuzzyfox", "Moonpaw88", "StarryWolf22" ):
        assert name.lower() not in texts.lower()
    assert "createdBy" not in texts

    listings = { r[ "thread_id" ]: r for r in conn.execute( "SELECT * FROM listings" ) }
    assert listings[ "a" ][ "sold" ] == 1 and listings[ "a" ][ "diamonds" ] == 1
    assert listings[ "b" ][ "sold" ] == 0
    assert conn.execute( "SELECT kind FROM comments WHERE thread_id='c'" ).fetchone()[ 0 ] == "iso"


def test_rerun_is_incremental( tmp_path ):
    conn = comments.connect( tmp_path / "w.db" )
    # Six old comments, 10 days apart, the newest one from 60 days ago
    old = [ thread( f"old{i}", T0 - ( 60 + 10 * i ) * DAY, "Pink for 1 dim", "u" ) for i in range( 6 ) ]
    first = FakeCommentsSession( old )
    comments.fetch_item_comments( conn, Wiki( first, pause=0 ), "Beard" )
    assert first.requests == 3      # first time it reads everything (2 per page)

    # Two new comments show up. Running again re-checks the 14 days before the
    # newest comment it had (in case of late "Sold!" replies), then stops
    new = [ thread( "new1", T0, "Yellow 2 dims", "u" ), thread( "new2", T0 - DAY, "Lf orange", "u" ) ]
    s = FakeCommentsSession( new + old )
    comments.fetch_item_comments( conn, Wiki( s, pause=0 ), "Beard" )

    assert conn.execute( "SELECT COUNT(*) FROM comments" ).fetchone()[ 0 ] == 8
    assert s.requests == 3          # 2 new + old0, old1 re-checked, stops at old2 and never reads page 4
