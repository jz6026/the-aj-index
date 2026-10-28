"""The chatbot. My own model figures out what a message wants; the answer always
comes from trade.py / the wiki, so it can never make up a value.

    message ──> intent (my model, or the rules until it's trained)
                  trade    -> trade.check()       "my blk long for 2 bad longs"
                  lookup   -> what the wiki says  "whats a pink beard worth"
                  compare  -> which is worth more "ly beard vs rim beard"
                  greeting / help / off_topic -> short canned answers

Usage (after `python3 -m ajworth.fetch`):
    python3 -m ajworth.chat "my blk long for 2 bad longs"     # one message
    python3 -m ajworth.chat                                   # chat back and forth (Enter to quit)
    python3 -m ajworth.chat --label                           # label real messages for training
    python3 -m ajworth.chat --train                           # train + test my intent model

Training data = ajworth/chat_examples.csv (starter examples, in the repo)
              + data/chat_labels.csv (what I label with --label).
The model has to beat the rules on messages it never saw, same deal as train.py.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .ladder import Ladder
from .match import Matcher
from .trade import Result, check, resolve

INTENTS = [ "trade", "lookup", "compare", "greeting", "help", "off_topic" ]
SEED = Path( __file__ ).with_name( "chat_examples.csv" )
LABELS = Path( "data/chat_labels.csv" )
MODEL = Path( "data/chat_model.joblib" )
SURE_ENOUGH = 0.45          # below this the model's guess is shaky, so the rules decide
MAX_LEN = 300
FOOTER = "AJ Item Worth Wiki · double-check before you accept"
EXAMPLE = 'Try something like "my blk long for 2 bad longs" or "whats a pink beard worth"'


# ---------------------------------------------------------------- privacy guard

# usernames, emails, phone numbers, "add me" etc. Lots of players are kids, so if a message
# has any of this we don't process it at all, and remind them not to share it.
PERSONAL = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+"                         # email
    r"|\b(?:\d[\s.-]?){7,}\b"                          # phone-ish
    r"|\bmy (?:user ?name|user|ign|discord|snap(?:chat)?|insta(?:gram)?|address|school|age) is\b"
    r"|\badd me\b|\bfriend me\b|\bbuddy me\b"
    r"|\b\w+#\d{4}\b",                                 # old discord tags
    re.IGNORECASE )


def has_personal_info( text: str ) -> bool:
    return bool( PERSONAL.search( text ) )


# ---------------------------------------------------------------- the rules (baseline to beat)

GREET = re.compile( r"^\s*(?:hi+|hey+|hello+|yo+|sup|heya|hiya|good (?:morning|afternoon|evening))\b[\s!.?]*(?:there)?[\s!.?]*$", re.I )
HELP = re.compile( r"\bhelp\b|how (?:do|does) (?:i|you|this|it)|what can you|what do i (?:type|say)|what are you\b", re.I )
COMPARE = re.compile( r"\bvs\.?\b|\bversus\b|worth (?:more|less)\b.*\b(?:than|or)\b|\bwhich (?:is|one)\b|\bmore than\b|\bless than\b|\bbetter\b.*\bor\b", re.I )
TRADE = re.compile( r"\bfor (?:my|their|ur|your|his|her|a|an|\d)|\b(?:my|their|ur)\b.*\bfor\b|\bw/?f\b|\bwfw\b|\boffered\b|\bwin or lose\b|\bwol\b|\+", re.I )
LOOKUP = re.compile( r"\bworth\b|\bvalue\b|\bhow much\b|\bpc\b|\bprice\b|\bwfl\b|\bhow many dims\b|\bgo for\b", re.I )


def rule_intent( text: str, is_reply: bool = False ) -> str:
    """Hand-written rules. Simple on purpose: my model has to do better than this."""
    if GREET.match( text ):
        return "greeting"
    if HELP.search( text ):
        return "help"
    if COMPARE.search( text ):
        return "compare"
    if TRADE.search( text ) or re.search( r"\bfor\b", text, re.I ):
        return "trade"
    if LOOKUP.search( text ):
        return "lookup"
    return "off_topic"


# ---------------------------------------------------------------- my model

def load_training() -> tuple[ list[ str ], list[ str ] ]:
    texts, labels = [], []
    for path in ( SEED, LABELS ):
        if path.exists():
            with path.open( newline="", encoding="utf-8" ) as f:
                for row in csv.DictReader( f ):
                    if row.get( "label" ) in INTENTS:
                        texts.append( row[ "text" ] )
                        labels.append( row[ "label" ] )
    return texts, labels


class Intents:
    """Picks the intent with my model if there's a trained one, otherwise the rules."""

    def __init__( self, model=None ):
        self.model = model

    @classmethod
    def load( cls, path: Path = MODEL ) -> "Intents":
        if path.exists():
            import joblib
            return cls( joblib.load( path ) )
        return cls()

    def guess( self, text: str ) -> tuple[ str, str, float ]:
        """( intent, who decided: "model" or "rules", how sure the model was )"""
        if self.model is None:
            return rule_intent( text ), "rules", 0.0
        from .train import prepare
        probs = self.model.predict_proba( [ prepare( text, False ) ] )[ 0 ]
        best = max( range( len( probs ) ), key=lambda i: probs[ i ] )
        if probs[ best ] < SURE_ENOUGH:
            return rule_intent( text ), "rules", float( probs[ best ] )
        return str( self.model.classes_[ best ] ), "model", float( probs[ best ] )


# ---------------------------------------------------------------- pulling the item names out

# words around the item that aren't part of it ("whats a ___ worth?")
LOOKUP_JUNK = re.compile(
    r"\b(?:what'?s|whats|what is|what are|how much (?:is|are|does|do)|how much|how many dims (?:is|are)|"
    r"value of|price check|pc(?: on)?|wfl|is the|is a|is an|worth|value|price|now|these days|still|"
    r"a lot|go for|pls|please|my|a|an|the|on)\b|[?!.,]", re.I )
COMPARE_SPLIT = re.compile( r"\bvs\.?\b|\bversus\b|\bmore than\b|\bless than\b|\bthan\b|\bor\b", re.I )
COMPARE_JUNK = re.compile(
    r"\b(?:which (?:one )?is (?:worth more|better|higher)|which one is better|which is worth more|whats better|"
    r"is (?:a|an|the)?|worth|more|less|better|higher|which|one|a|an|the)\b|[?!.,:]", re.I )


def _clean( text: str, junk: re.Pattern ) -> str:
    return re.sub( r"\s+", " ", junk.sub( " ", text ) ).strip()


def lookup_name( text: str ) -> str:
    return _clean( text, LOOKUP_JUNK )


def compare_names( text: str ) -> tuple[ str, str ] | None:
    parts = [ _clean( p, COMPARE_JUNK ) for p in COMPARE_SPLIT.split( text ) ]
    parts = [ p for p in parts if p ]
    return ( parts[ 0 ], parts[ 1 ] ) if len( parts ) >= 2 else None


# ---------------------------------------------------------------- answers

@dataclass
class Reply:
    intent: str
    decided_by: str                     # "model" or "rules" (or "guard")
    text: str                           # what the chatbot says
    trade: dict | None = None           # the full trade.check result, for the website to show
    items: list[ dict ] = field( default_factory=list )

    def to_dict( self ) -> dict:
        return { "intent": self.intent, "decided_by": self.decided_by, "text": self.text,
                 "trade": self.trade, "items": self.items }


def _quote( line ) -> str:
    """'2 x Beard - Pink: "A Few RIMs"', word for word from the wiki."""
    name = line.name or line.text
    if line.qty != 1:
        name = f"{line.qty:g} x {name}"
    return f'{name}: "{line.wiki}"' if line.wiki else name


def _trade_text( r: Result ) -> str:
    lines = [ r.message ]
    if r.give:
        lines.append( "You give: " + ", ".join( _quote( l ) for l in r.give ) )
    if r.get:
        lines.append( "You get: " + ", ".join( _quote( l ) for l in r.get ) )
    lines += r.notes[ :3 ]               # short! they're mid-trade
    return "\n".join( lines + [ FOOTER ] )


def answer_trade( text: str, matcher: Matcher, ladder: Ladder ) -> Reply:
    r = check( text, matcher, ladder )
    return Reply( "trade", "", _trade_text( r ), trade=r.to_dict() )


def answer_lookup( text: str, matcher: Matcher, ladder: Ladder ) -> Reply:
    name = lookup_name( text )
    if not name:
        return Reply( "lookup", "", "Which item? " + EXAMPLE )
    line = resolve( name, matcher, ladder )
    if line.status == "ask":
        return Reply( "lookup", "", "Which one? These are worth different things:\n" + "\n".join( line.options ) )
    if line.status == "unknown":
        return Reply( "lookup", "", f'Couldn\'t find "{name}" on the wiki. Try another name for it?' )
    if line.wiki is None:
        return Reply( "lookup", "", f"{line.name} is one of the wiki's value units, not an item.\n{FOOTER}" )
    return Reply( "lookup", "", f"{_quote( line )}\n{FOOTER}",
                  items=[ { "name": line.name, "worth": line.wiki } ] )


def answer_compare( text: str, matcher: Matcher, ladder: Ladder ) -> Reply:
    names = compare_names( text )
    if not names:
        return Reply( "compare", "", 'Compare which two? Like "ly beard vs rim beard"' )
    a, b = names
    r = check( f"my {a} for their {b}", matcher, ladder )      # same math as a trade, different wording
    if r.verdict == "good":
        head = f"{r.get[ 0 ].name or b} is worth more."
    elif r.verdict in ( "over", "way_over" ):
        head = f"{r.give[ 0 ].name or a} is worth more."
    elif r.verdict == "close":
        head = "They're about the same."
    else:
        head = "Can't compare these yet."
    lines = [ head ] + [ _quote( l ) for l in r.give + r.get if l.wiki ]
    notes = [ n for n in r.notes if "assumed" not in n and "What are you getting" not in n ]
    return Reply( "compare", "", "\n".join( lines + notes[ :2 ] + [ FOOTER ] ), trade=r.to_dict() )


CANNED = {
    "greeting": "Hey! Tell me a trade and I'll check it against the AJ Item Worth Wiki. " + EXAMPLE,
    "help": ( "I check Animal Jam Classic trades using the AJ Item Worth Wiki.\n"
              '- Trades: "my blk long for 2 bad longs"\n'
              '- Prices: "whats a pink beard worth"\n'
              '- Compare: "ly beard vs rim beard"\n'
              "I only know what the wiki says, so always double-check before you accept!" ),
    "off_topic": "I only know AJ trades lol. " + EXAMPLE,
}


def respond( text: str, matcher: Matcher, ladder: Ladder, intents: Intents ) -> Reply:
    text = ( text or "" ).strip()[ :MAX_LEN ]
    if not text:
        return Reply( "help", "rules", CANNED[ "help" ] )
    if has_personal_info( text ):
        return Reply( "off_topic", "guard",
                      "Heads up: don't share usernames or contact info here (or with people you trade with "
                      "online). I don't need any of that, just the items! " + EXAMPLE )
    intent, who, _ = intents.guess( text )
    if intent == "trade":
        reply = answer_trade( text, matcher, ladder )
    elif intent == "lookup":
        reply = answer_lookup( text, matcher, ladder )
    elif intent == "compare":
        reply = answer_compare( text, matcher, ladder )
    else:
        reply = Reply( intent, "", CANNED[ intent ] )
    reply.decided_by = who
    return reply


# ---------------------------------------------------------------- labeling + training

KEYS = { "t": "trade", "l": "lookup", "c": "compare", "g": "greeting", "h": "help", "o": "off_topic" }


def label_pool( conn, seed: int | None = None ) -> list[ str ]:
    """Real player wording to label: wiki comments that look like trades or questions.
    (Later: real chats from the site, once people use it.)"""
    rows = conn.execute( "SELECT text FROM comments WHERE kind IN ('trade', 'question', 'iso') "
                         "AND LENGTH(text) < 160" ).fetchall()
    texts = list( dict.fromkeys( r[ 0 ] for r in rows ) )
    random.Random( seed ).shuffle( texts )
    return texts


def label( conn ) -> None:
    done = set( load_training()[ 0 ] )
    pool = [ t for t in label_pool( conn ) if t not in done ]
    if not pool:
        print( "Nothing to label. Collect comments first: python3 -m ajworth.comments" )
        return
    print( "Enter = agree with the guess, or: " + "  ".join( f"{k}={v}" for k, v in KEYS.items() ) +
           "  x=skip  quit=stop\n(label it as if someone typed it to the chatbot)\n" )
    LABELS.parent.mkdir( parents=True, exist_ok=True )
    new = not LABELS.exists()
    with LABELS.open( "a", newline="", encoding="utf-8" ) as f:
        w = csv.DictWriter( f, fieldnames=[ "text", "label" ] )
        if new:
            w.writeheader()
        for i, text in enumerate( pool, 1 ):
            guess = rule_intent( text )
            ans = input( f"[{i}] {text[ :150 ]!r}\n     guess: {guess} > " ).strip().lower()
            if ans == "quit":
                break
            if ans == "x":
                continue
            lab = guess if ans == "" else KEYS.get( ans )
            if lab is None:
                print( "     ?? keys: " + " ".join( f"{k}={v}" for k, v in KEYS.items() ) )
                continue
            w.writerow( { "text": text, "label": lab } )
            f.flush()                    # saved right away, quit whenever


def train( explain: bool = False ) -> None:
    import joblib
    from .train import build_model, evaluate, prepare

    texts, labels = load_training()
    print( f"{len( texts )} examples ({SEED.name} + {LABELS})\n" )
    acc_rules, acc_model = evaluate( texts, [ False ] * len( texts ), labels, explain=explain,
                                     rules=lambda t, r: rule_intent( t ), noun="messages" )
    if acc_model < acc_rules:
        # only switch the chatbot over once my model actually wins
        if MODEL.exists():
            MODEL.unlink()
        print( f"\nThe rules still win, so the chatbot keeps using them. Label more real messages "
               f"(python3 -m ajworth.chat --label) and train again!" )
        return
    final = build_model().fit( [ prepare( t, False ) for t in texts ], labels )
    MODEL.parent.mkdir( parents=True, exist_ok=True )
    joblib.dump( final, MODEL )
    print( f"\nMy model wins! Saved to {MODEL}, and the chatbot uses it from now on." )


# ---------------------------------------------------------------- command line

def main():
    ap = argparse.ArgumentParser( description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter )
    ap.add_argument( "message", nargs="*" )
    ap.add_argument( "--db", help="SQLite file or postgresql:// URL (default: DATABASE_URL, else data/worth.db)" )
    ap.add_argument( "--label", action="store_true", help="label real messages for training" )
    ap.add_argument( "--train", action="store_true", help="train + test my intent model" )
    ap.add_argument( "--explain", action="store_true", help="with --train: show the words each intent leans on" )
    args = ap.parse_args()

    if args.train:
        return train( args.explain )
    conn = store.connect( args.db )
    if args.label:
        return label( conn )

    matcher, ladder, intents = Matcher.from_db( conn ), Ladder.load( conn ), Intents.load()

    def say( msg: str ):
        r = respond( msg, matcher, ladder, intents )
        print( f"[{r.intent} via {r.decided_by}]\n{r.text}\n" )

    if args.message:
        return say( " ".join( args.message ) )
    print( "Chat with the bot (Enter on an empty line to quit)\n" )
    while ( msg := input( "you> " ).strip() ):
        say( msg )


if __name__ == "__main__":
    main()
