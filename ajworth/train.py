"""Trains my own comment classifier and checks if it actually beats the rules.

Usage (after labeling with `python3 -m ajworth.label`):
    python3 -m ajworth.train                     # train, test, save data/model.joblib
    python3 -m ajworth.train --explain           # also show the words each label leans on
    python3 -m ajworth.train --try "pink 4 dims"  # ask the saved model about one comment

How it works:
  1. Each comment gets turned into counts of its words and word pairs ("1 dim",
     "jag me"), plus little letter chunks ("dim", "im ", "lf!") so slang and typos
     still work. Numbers all become 0 so "1 dim" and "80 dims" look the same.
     Replies get marked, since "sold!" means more when it's a reply.
  2. Logistic regression learns how much each count matters for each label.
     Whichever label scores highest wins.
  3. 20% of your labels get hidden away as a test the model never sees.
     The rules and the model both take that test, so it's a fair fight.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

from .tagger import tag

MIN_LABELS = 60          # fewer than this and the scores don't really mean anything
REPLY_MARK = "__reply__ "


def prepare( text: str, is_reply: bool ) -> str:
    text = re.sub( r"\[user\]", " ", text.lower() )
    text = re.sub( r"\d+(?:[.,]\d+)?k?", "0", text )
    return ( REPLY_MARK if is_reply else "" ) + text


def build_model():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline

    features = FeatureUnion( [
        ( "words", TfidfVectorizer( ngram_range=( 1, 2 ), token_pattern=r"[a-z0-9_']+|[!?]", min_df=1 ) ),
        ( "chunks", TfidfVectorizer( analyzer="char_wb", ngram_range=( 2, 4 ), min_df=2 ) ),
    ] )
    return Pipeline( [
        ( "features", features ),
        ( "clf", LogisticRegression( max_iter=3000, class_weight="balanced", C=5.0 ) ),
    ] )


def load( path: Path ) -> tuple[ list[ str ], list[ bool ], list[ str ] ]:
    with path.open( newline="", encoding="utf-8" ) as f:
        rows = list( csv.DictReader( f ) )
    texts = [ r[ "text" ] for r in rows ]
    replies = [ str( r.get( "is_reply", "0" ) ) in ( "1", "True", "true" ) for r in rows ]
    labels = [ r[ "label" ] for r in rows ]
    return texts, replies, labels


def evaluate( texts, replies, labels, seed: int = 0, explain: bool = False, out=print,
              rules=None, noun: str = "comments" ):
    """rules( text, is_reply ) -> label is the baseline to beat (default: the comment tagger).
    chat.py reuses this with its own rules."""
    rules = rules or ( lambda t, r: tag( t, r ).kind )
    from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split

    counts = Counter( labels )
    # If a label only has 1 example we can't test on it, so it just goes in training
    can_split = [ i for i, y in enumerate( labels ) if counts[ y ] >= 2 ]
    solo = [ i for i, y in enumerate( labels ) if counts[ y ] < 2 ]
    tr, te = train_test_split( can_split, test_size=0.2, random_state=seed,
                              stratify=[ labels[ i ] for i in can_split ] )
    tr = list( tr ) + solo

    X = [ prepare( t, r ) for t, r in zip( texts, replies ) ]
    model = build_model().fit( [ X[ i ] for i in tr ], [ labels[ i ] for i in tr ] )

    y_true = [ labels[ i ] for i in te ]
    y_model = list( model.predict( [ X[ i ] for i in te ] ) )
    y_rules = [ rules( texts[ i ], replies[ i ] ) for i in te ]

    acc_rules, acc_model = accuracy_score( y_true, y_rules ), accuracy_score( y_true, y_model )
    out( f"Trained on {len(tr)} {noun}, tested on {len(te)} it never saw.\n" )
    out( f"  rules accuracy:     {acc_rules:6.1%}" )
    out( f"  my model accuracy:  {acc_model:6.1%}\n" )

    names = sorted( set( labels ) )
    out( classification_report( y_true, y_model, labels=names, zero_division=0 ) )
    out( "Confusion matrix (rows = your label, columns = model's guess):" )
    out( "            " + " ".join( f"{n[:8]:>8}" for n in names ) )
    for name, row in zip( names, confusion_matrix( y_true, y_model, labels=names ) ):
        out( f"  {name:>8}  " + " ".join( f"{v:>8}" for v in row ) )

    misses = [ ( texts[ i ], labels[ i ], p ) for i, p in zip( te, y_model ) if p != labels[ i ] ]
    if misses:
        out( f"\nSome {noun} it got wrong (you said → model said):" )
        for t, y, p in misses[ :8 ]:
            out( f"  {y:>8} → {p:<8} {t[:70]!r}" )

    if explain:
        explain_model( model, out )
    return acc_rules, acc_model


def explain_model( model, out=print, top: int = 8 ):
    """Shows the words that push the model hardest toward each label."""
    feats = model.named_steps[ "features" ]
    vocab = []
    for name, vec in feats.transformer_list:
        prefix = "" if name == "words" else "~"
        vocab += [ prefix + v for v in vec.get_feature_names_out() ]
    clf = model.named_steps[ "clf" ]
    out( "\nWhat each label leans on (~ = letter chunk):" )
    rows = clf.coef_ if len( clf.classes_ ) > 2 else [ -clf.coef_[ 0 ], clf.coef_[ 0 ] ]
    for label, weights in zip( clf.classes_, rows ):
        best = sorted( range( len( weights ) ), key=lambda j: -weights[ j ] )[ :top ]
        out( f"  {label:>8}: " + ", ".join( repr( vocab[ j ] ) for j in best ) )


def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "--labels", default="data/labels.csv" )
    ap.add_argument( "--model", default="data/model.joblib" )
    ap.add_argument( "--explain", action="store_true" )
    ap.add_argument( "--try", dest="try_text", help="classify one comment with the saved model" )
    ap.add_argument( "--reply", action="store_true", help="with --try: treat it as a reply" )
    args = ap.parse_args()

    import joblib

    if args.try_text:
        model = joblib.load( args.model )
        x = prepare( args.try_text, args.reply )
        probs = dict( zip( model.classes_, model.predict_proba( [ x ] )[ 0 ] ) )
        rule = tag( args.try_text, args.reply ).kind
        print( f"model: {max(probs, key=probs.get)}   rules: {rule}" )
        print( "  " + ", ".join( f"{k} {v:.0%}" for k, v in sorted( probs.items(), key=lambda kv: -kv[ 1 ] ) ) )
        return

    path = Path( args.labels )
    if not path.exists():
        print( "No labels yet. Run `python3 -m ajworth.label` first." )
        return
    texts, replies, labels = load( path )
    if len( labels ) < MIN_LABELS:
        print( f"Only {len(labels)} labels so far. Aim for at least {MIN_LABELS} "
              f"(a few hundred is better) before the scores mean much." )
        return

    evaluate( texts, replies, labels, explain=args.explain )

    final = build_model().fit( [ prepare( t, r ) for t, r in zip( texts, replies ) ], labels )
    Path( args.model ).parent.mkdir( parents=True, exist_ok=True )
    joblib.dump( final, args.model )
    print( f"\nSaved a model trained on all {len(labels)} labels to {args.model}" )


if __name__ == "__main__":
    main()
