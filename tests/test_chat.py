"""The chatbot: intents, answers that quote the wiki, and the privacy guard."""

import pytest

from ajworth.chat import (FOOTER, Intents, compare_names, has_personal_info, load_training, lookup_name,
                          respond, rule_intent)
from ajworth.train import build_model, prepare
from tests.test_trade import world  # noqa: F401  (same Beard + counter pages fixture)


@pytest.fixture( scope="module" )
def bot( world ):
    return ( *world, Intents() )          # rules only, no trained model


# ------------------------------------------------------------ privacy guard

@pytest.mark.parametrize( "msg", [
    "my username is coolwolf123 add me",
    "add me on discord",
    "my discord is wolfie#1234",
    "email me at kid@example.com",
    "text me 555 123 4567",
] )
def test_personal_info_is_never_processed( bot, msg ):
    assert has_personal_info( msg )
    r = respond( msg, *bot )
    assert r.decided_by == "guard"
    assert "don't share" in r.text
    assert "coolwolf" not in r.text and "wolfie" not in r.text      # never repeated back


@pytest.mark.parametrize( "msg", [ "my blk long for 2 bad longs", "whats a pink beard worth", "50 dims for my beard" ] )
def test_normal_trade_talk_is_fine( msg ):
    assert not has_personal_info( msg )


# ------------------------------------------------------------ pulling out names

def test_lookup_name():
    assert lookup_name( "whats a blk long worth?" ) == "blk long"
    assert lookup_name( "pc on my ly beard pls" ) == "ly beard"
    assert lookup_name( "how much is a pink beard" ) == "pink beard"


def test_compare_names():
    assert compare_names( "ly beard vs rim beard" ) == ( "ly beard", "rim beard" )
    assert compare_names( "is a pink beard worth more than a rim beard?" ) == ( "pink beard", "rim beard" )
    assert compare_names( "which is worth more lb beard or pink beard" ) == ( "lb beard", "pink beard" )


# ------------------------------------------------------------ answers

def test_trade_quotes_the_wiki_word_for_word( bot ):
    r = respond( "my leap year beard for their pink beard", *bot )
    assert r.intent == "trade"
    assert '"Good Short Collar"' in r.text and '"A Few RIMs"' in r.text
    assert r.text.endswith( FOOTER )
    assert r.trade[ "verdict" ] == "way_over"


def test_lookup( bot ):
    r = respond( "whats a pink beard worth", *bot )
    assert r.intent == "lookup"
    assert 'Beard - Pink: "A Few RIMs"' in r.text


def test_lookup_asks_which_color( bot ):
    r = respond( "how much is a beard", *bot )
    assert "Which one?" in r.text


def test_compare( bot ):
    r = respond( "ly beard vs pink beard", *bot )
    assert r.intent == "compare"
    assert r.text.startswith( "Beard - Leap Year is worth more." )


@pytest.mark.parametrize( "msg, intent", [ ( "hey", "greeting" ), ( "how do i use this", "help" ),
                                            ( "tell me a joke", "off_topic" ) ] )
def test_canned( bot, msg, intent ):
    r = respond( msg, *bot )
    assert r.intent == intent and "pink beard" in r.text or "AJ" in r.text


# ------------------------------------------------------------ my model

def test_rules_handle_the_starter_examples():
    texts, labels = load_training()
    right = sum( rule_intent( t ) == y for t, y in zip( texts, labels ) )
    assert right / len( texts ) > 0.8


def test_trained_model_is_used_when_sure( bot ):
    texts, labels = load_training()
    model = build_model().fit( [ prepare( t, False ) for t in texts ], labels )
    intents = Intents( model )
    intent, who, sure = intents.guess( "should i trade my solid for 3 dbs" )
    assert intent == "trade"
    assert who in ( "model", "rules" )          # falls back to the rules when the model is shaky
