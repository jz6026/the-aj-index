"""Simple rules that guess what kind of comment something is. My model has to beat these!

kind:
    sale      a listing with a price or shop mention ("Yellow for 1 dim", "12.5k gems", "fs")
    sold      a reply confirming a deal happened ("Sold!", "bought it", "traded")
    iso       someone looking to buy ("ISO", "looking for", "lf")
    question  asking about worth ("what's this worth?", "how much ...?")
    trade     item-for-item offers ("ft", "any offers?", "my orange for a cb")
    other     everything else (mostly conversation)

Prices: diamonds ("1 dim", "80 dims", "5-10 diamonds") and gems ("12.5k gems",
"5000 gems") get pulled out separately. A range like 5-10 becomes the middle (7.5).

These are simple on purpose. They give the model something fair to compete
against ("rules get X% right, my model gets Y%").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NUM = r"(\d+(?:[.,]\d+)?)\s*(k)?"
_PRICE = {
    "diamonds": re.compile( rf"(?<![\w.]){_NUM}\s*(?:(?:-|to)\s*{_NUM})?\s*(?:dims?|diamonds?|💎)(?!\w)",
                           re.IGNORECASE ),
    "gems": re.compile( rf"(?<![\w.]){_NUM}\s*(?:(?:-|to)\s*{_NUM})?\s*(?:gems?)(?!\w)", re.IGNORECASE ),
}
_SOLD = re.compile( r"\b(sold|bought( it)?|got it|purchased|ty for buying|traded|deal done)\b",
                   re.IGNORECASE )
_ISO = re.compile( r"\b(iso|lf|looking for|in search of|want(ing|s)? to buy|buying)\b", re.IGNORECASE )
_SALE = re.compile( r"\b(fs|for sale|selling|sell(?:ing)? for|shops?)\b", re.IGNORECASE )
_TRADE = re.compile( r"\b(ft|for trade|trading|trade|trd|any offers?|offers?|offering|"
                    r"colou?r ?swap(?:ping)?)\b", re.IGNORECASE )
# If someone mentions cbs, dbs, longs etc. they're probably offering a trade
_TRADE_UNITS = re.compile( r"\b(cbs?|dbs?|betas?|longs?|shorts?|wrists?|collars?|rims?|spikes?)\b",
                          re.IGNORECASE )
_QUESTION = re.compile( r"(\bworth\b.*\?|\bhow much\b|\bwhat.{0,15}worth\b|\bwfw\b)", re.IGNORECASE )


@dataclass
class Tag:
    kind: str
    diamonds: float | None = None
    gems: float | None = None


def _amount( num: str | None, k: str | None ) -> float | None:
    if num is None:
        return None
    return float( num.replace( ",", "" ) ) * ( 1000 if k else 1 )


def price( text: str, currency: str ) -> float | None:
    """'80 dims' -> 80, '5-10 diamonds' -> 7.5, '12.5k gems' -> 12500, no price -> None."""
    m = _PRICE[ currency ].search( text )
    if not m:
        return None
    lo = _amount( m.group( 1 ), m.group( 2 ) )
    hi = _amount( m.group( 3 ), m.group( 4 ) or m.group( 2 ) ) if m.group( 3 ) else lo
    return ( lo + hi ) / 2


def tag( text: str, is_reply: bool = False ) -> Tag:
    dims, gems = price( text, "diamonds" ), price( text, "gems" )
    if _SOLD.search( text ) and ( is_reply or len( text ) < 25 ):
        return Tag( "sold" )
    if _ISO.search( text ):
        return Tag( "iso", dims, gems )
    if dims is not None or gems is not None or _SALE.search( text ):
        return Tag( "sale", dims, gems )
    if _QUESTION.search( text ):
        return Tag( "question" )
    if _TRADE.search( text ) or _TRADE_UNITS.search( text ):
        return Tag( "trade" )
    return Tag( "other" )
