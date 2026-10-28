import json
from pathlib import Path

from ajworth import store
from ajworth.fetch import Wiki, refresh

BEARD = ( Path( __file__ ).parent / "fixtures" / "beard.wikitext" ).read_text()
OLD_BEARD = BEARD.replace( "Good [[Rare Short Spiked Collar|Short Collar]]", "Good Long Wrist" ) \
                 .replace( "September 19, 2026", "December 18, 2025" )


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__( self, data ):
        self._data = data
        self.text = json.dumps( data )

    def json( self ):
        return self._data

    def raise_for_status( self ):
        pass


class FakeSession:
    """Pretends to be the wiki, answering the two API calls the fetcher makes."""

    def __init__( self, pages ):          # {title: (rev_id, wikitext)}
        self.pages, self.headers = pages, {}

    def get( self, url, params, timeout ):
        if params.get( "list" ) == "categorymembers":
            return FakeResponse( { "query": { "categorymembers": [ { "title": t } for t in self.pages ] } } )
        out = []
        for t in params[ "titles" ].split( "|" ):
            rev, text = self.pages[ t ]
            out.append( { "title": t, "revisions": [ { "revid": rev, "timestamp": "2026-09-19T00:00:00Z",
                                                   "slots": { "main": { "content": text } } } ] } )
        return FakeResponse( { "query": { "pages": out } } )


def test_history_accumulates_only_on_change( tmp_path, db_target ):
    conn = store.connect( db_target )

    # Day 1: the old version of the page
    s1 = refresh( conn, Wiki( FakeSession( { "Beard": ( 100, OLD_BEARD ) } ), pause=0 ), log=lambda *_: None )
    assert s1[ "changed" ] == 1

    # Day 2: same version again, so nothing new gets saved
    s2 = refresh( conn, Wiki( FakeSession( { "Beard": ( 100, OLD_BEARD ) } ), pause=0 ), log=lambda *_: None )
    assert s2[ "changed" ] == 0

    # Day 3: someone edited the wiki and the Leap Year value dropped
    refresh( conn, Wiki( FakeSession( { "Beard": ( 200, BEARD ) } ), pause=0 ), log=lambda *_: None )

    history = [ r[ "worth_raw" ] for r in conn.execute(
        "SELECT worth_raw FROM worth_snapshots WHERE variant='Leap Year' ORDER BY rev_id" ) ]
    assert history == [ "Good Long Wrist", "Good Short Collar" ]

    current = conn.execute( "SELECT worth_raw FROM current_worth WHERE variant='Leap Year'" ).fetchall()
    assert [ r[ 0 ] for r in current ] == [ "Good Short Collar" ]

    n = store.export_json( conn, tmp_path / "items.json" )
    assert n == 11
    assert ( "A Few RIMs", 8 ) in store.label_counts( conn )


def test_reparse_fixes_old_values_without_downloading( tmp_path, db_target ):
    from ajworth.parse import parse_page
    conn = store.connect( db_target )
    text = ( Path( __file__ ).parent / "fixtures" / "cupid_wings.wikitext" ).read_text()
    # pretend an older parser only found the "Other Variants" table
    old = parse_page( "Cupid Wings", text )
    old.variants = [ v for v in old.variants if v.section == "Other Variants" ]
    store.save_page( conn, old, 7, None, wikitext=text )
    assert conn.execute( "SELECT COUNT(*) FROM current_worth" ).fetchone()[ 0 ] == 9

    assert store.reparse( conn, parse_page ) == 1
    assert conn.execute( "SELECT COUNT(*) FROM current_worth" ).fetchone()[ 0 ] == 24
    assert store.reparse( conn, parse_page ) == 0                 # nothing left to fix
