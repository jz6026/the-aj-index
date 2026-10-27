"""Trains on made-up comments to make sure the whole thing runs and actually learns."""

import csv
import random

from ajworth import label, train

COLORS = [ "pink", "yellow", "orange", "brown", "light brown", "silver", "black", "black & white" ]
ITEMS = [ "art easel", "worn blanket", "rare beard", "spiked wristband", "fox hat", "lamp", "crown" ]


def fake_labeled( n_per=25, seed=1 ):
    r = random.Random( seed )
    c, i = lambda: r.choice( COLORS ), lambda: r.choice( ITEMS )
    gen = {
        "sale": [ lambda: f"{c()} for {r.randint(1, 90)} dims [user]",
                 lambda: f"selling {c()} in my shop [user]",
                 lambda: f"{c()} {r.randint(2, 20)}k gems @[user]" ],
        "sold": [ lambda: r.choice( [ "Sold!!", "sold :)", "traded sorry", "Bought it, ty!" ] ) ],
        "iso":  [ lambda: f"lf {c()}! jag me",
                 lambda: f"desperately iso {c()} !!",
                 lambda: f"looking for {c()} beard, will buy" ],
        # trade offers the rules usually miss since there's no "ft" or "trade" in them
        "trade": [ lambda: f"{c()} and {c()} for your {i()}?",
                  lambda: f"would you take a {i()} for it?",
                  lambda: f"my {c()} for your {i()}?" ],
        "question": [ lambda: f"what is the {c()} one worth?", lambda: f"how much is {c()} now?" ],
        "other": [ lambda: r.choice( [ "I remember when this was rare", "Ok :>", "great!",
                                    "can you get on tomorrow?", "i still have it" ] ) ],
    }
    rows = []
    for lab, makers in gen.items():
        for _ in range( n_per ):
            rows.append( ( r.choice( makers )(), lab == "sold", lab ) )
    r.shuffle( rows )
    return rows


def test_learns_and_beats_rules_on_keywordless_trades():
    rows = fake_labeled()
    texts, replies, labels = map( list, zip( *rows ) )
    lines = []
    acc_rules, acc_model = train.evaluate( texts, replies, labels, explain=True, out=lines.append )
    assert acc_model > 0.85
    assert acc_model > acc_rules           # the rules can't catch these trades but the model should
    assert any( "What each label leans on" in l for l in lines )


def test_prepare_normalizes_numbers_names_and_replies():
    assert train.prepare( "Pink for 80 Dims [user]", False ) == "pink for 0 dims  "
    assert train.prepare( "12.5k gems", False ) == "0 gems"
    assert train.prepare( "Sold!", True ).startswith( train.REPLY_MARK )


def test_label_file_roundtrip_and_candidate_mixing( tmp_path ):
    from ajworth import comments
    conn = comments.connect( tmp_path / "w.db" )
    conn.executemany(
        "INSERT INTO comments (post_id, thread_id, title, is_reply, created, text, kind, fetched_at) "
        "VALUES (?, ?, 'Beard', 0, '2026-01-01', ?, ?, 'now')",
        [ ( f"s{n}", f"s{n}", "1 dim", "sale" ) for n in range( 5 ) ] + [ ( "i1", "i1", "lf pink", "iso" ) ],
    )
    order = [ r[ "kind" ] for r in label.candidates( conn, done={ "s0" }, seed=0 ) ]
    assert len( order ) == 5 and "iso" in order[ :2 ]      # rarer kinds don't get stuck at the end

    out = tmp_path / "labels.csv"
    label.append_label( out, { "post_id": "i1", "is_reply": 0, "text": "lf pink", "label": "iso",
                             "rule_guess": "iso" } )
    assert label.load_labels( out )[ "i1" ][ "label" ] == "iso"
    with out.open() as f:
        assert next( csv.reader( f ) ) == label.FIELDS
