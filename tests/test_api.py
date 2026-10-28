from fastapi.testclient import TestClient

from ajworth import store
from ajworth import api
from ajworth.api import app
from ajworth.fetch import Wiki, refresh
from tests.test_fetch_store import BEARD, FakeSession


def client_with_beard( db_target, monkeypatch ):
    conn = store.connect( db_target )
    refresh( conn, Wiki( session=FakeSession( { "Beard": ( 1, BEARD ) } ), pause=0 ), log=lambda *a: None )
    conn.close()
    monkeypatch.setenv( "DATABASE_URL", str( db_target ) )
    monkeypatch.setattr( api, "_cache", { "at": 0.0, "matcher": None, "ladder": None } )   # fresh per test
    return TestClient( app )


def test_health():
    assert TestClient( app ).get( "/api/health" ).json() == { "ok": True }


def test_search_and_lookup_quote_the_wiki_exactly( db_target, monkeypatch ):
    c = client_with_beard( db_target, monkeypatch )

    found = c.get( "/api/items", params={ "q": "BEA" } ).json()[ "results" ]
    assert found[ 0 ][ "title" ] == "Beard"

    item = c.get( "/api/items/Beard" ).json()
    worths = { v[ "worth" ] for v in item[ "variants" ] }
    assert "A Few RIMs" in worths                     # word for word, no unit conversion
    assert "CC BY-SA" in item[ "credit" ]
    assert item[ "wiki_url" ].endswith( "/wiki/Beard" )


def test_unknown_item_and_sneaky_search( db_target, monkeypatch ):
    c = client_with_beard( db_target, monkeypatch )
    assert c.get( "/api/items/Not A Real Thing" ).status_code == 404
    assert c.get( "/api/items", params={ "q": "%" } ).json()[ "results" ] == []   # % isn't a wildcard


def test_trade_check_goes_through_trade_py( db_target, monkeypatch ):
    c = client_with_beard( db_target, monkeypatch )
    r = c.get( "/api/trade", params={ "q": "my beard for your beard" } ).json()
    assert r[ "verdict" ] and r[ "message" ]
    assert r[ "give" ][ 0 ][ "text" ] and r[ "get" ][ 0 ][ "text" ]
    assert "CC BY-SA" in r[ "credit" ]
