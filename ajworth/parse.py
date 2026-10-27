"""Takes one AJ Item Worth Wiki page (the raw wikitext) and turns it into neat rows.

Worth pages are basically wiki tables that look like this:

    header row   ! Black & Red/Default ! Orange ! ...   -> variant names
    image row    | [[File:Beard1.png]]  | ...           -> variant pictures
    value row    | A Few [[Obtainable RIMs|RIMs]] | ... -> worth labels

Sometimes one table repeats that header/image/value pattern a bunch of times, and
some pages have several tables under different headings ("Other Variants",
"Den Items", ...). So we just go row by row and match each value row with the
last header row we saw, which handles all of those layouts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime

import mwparserfromhell

LAST_UPDATED_RE = re.compile( r"Last Updated\s+([A-Z][a-z]+ \d{1,2}, \d{4})" )
FILE_RE = re.compile( r"\[\[\s*(?:File|Image)\s*:\s*([^|\]]+)", re.IGNORECASE )
HEADING_RE = re.compile( r"^(={2,6})\s*(.*?)\s*\1\s*$" )
CATEGORY_RE = re.compile( r"\[\[\s*Category\s*:\s*([^\]|]+)", re.IGNORECASE )


@dataclass
class Variant:
    item: str            # the page title, like "Beard"
    variant: str         # the column header, like "Black & White"
    section: str         # which heading the table is under ("" if it's at the top)
    worth_raw: str       # the worth exactly how the wiki says it, like "A Few RIMs"
    image: str | None    # the picture's file name, like "Beard2.png"


@dataclass
class ItemPage:
    title: str
    last_updated: str | None          # the date, like "2026-09-19"
    categories: list[ str ] = field( default_factory=list )
    variants: list[ Variant ] = field( default_factory=list )

    def to_dict( self ) -> dict:
        return asdict( self )


def clean( text: str ) -> str:
    """Wikitext -> plain text. [[A|B]] becomes B, and files, bold, weird spaces get cleaned out."""
    plain = mwparserfromhell.parse( text ).strip_code( normalize=True, collapse=True )
    plain = plain.replace( " ", " " )
    return re.sub( r"\s+", " ", plain ).strip()


def _split_cells( line: str, sep: str ) -> list[ str ]:
    """Splits '! a !! b' or '| a || b' into its cells (and drops any style stuff in front)."""
    body = line[ 1: ]
    parts = body.split( sep * 2 )
    cells = []
    for part in parts:
        # Some cells start with style stuff like `style="..." |content`.
        # The first | only counts as the divider if what's before it looks like
        # style stuff (has an '='), and it isn't the | inside a [[link|label]].
        depth, cut = 0, None
        for i, ch in enumerate( part ):
            if part.startswith( "[[", i ):
                depth += 1
            elif part.startswith( "]]", i ):
                depth -= 1
            elif ch == "|" and depth == 0:
                cut = i
                break
        if cut is not None and "=" in part[ :cut ]:
            part = part[ cut + 1: ]
        cells.append( part.strip() )
    return cells


def _parse_date( raw: str ) -> str | None:
    try:
        return datetime.strptime( raw, "%B %d, %Y" ).date().isoformat()
    except ValueError:
        return None


def parse_page( title: str, wikitext: str ) -> ItemPage:
    m = LAST_UPDATED_RE.search( wikitext )
    page = ItemPage(
        title=title,
        last_updated=_parse_date( m.group( 1 ) ) if m else None,
        categories=[ c.strip() for c in CATEGORY_RE.findall( wikitext ) ],
    )

    section = ""
    in_table = False
    rows: list[ tuple[ str, list[ str ] ] ] = []   # (kind, cells) for the table we're in
    current: tuple[ str, list[ str ] ] | None = None

    def flush_table():
        headers: list[ str ] = []
        images: list[ str | None ] = []
        for kind, cells in rows:
            if kind == "header":
                headers = [ clean( c ) for c in cells ]
                images = [ None ] * len( headers )
                continue
            files = [ FILE_RE.search( c ) for c in cells ]
            if cells and all( files ):
                images = [ f.group( 1 ).strip() for f in files ]
                continue
            if not headers:
                continue
            for i, cell in enumerate( cells[ : len( headers ) ] ):
                worth = clean( cell )
                if not worth or not headers[ i ]:
                    continue
                page.variants.append( Variant(
                    item=title,
                    variant=headers[ i ],
                    section=section,
                    worth_raw=worth,
                    image=images[ i ] if i < len( images ) else None,
                ) )

    for raw_line in wikitext.splitlines():
        line = raw_line.strip()
        if not in_table:
            h = HEADING_RE.match( line )
            if h:
                section = clean( h.group( 2 ) )
            if line.startswith( "{|" ):
                in_table, rows, current = True, [], None
            continue

        if line.startswith( "|}" ):
            if current and current[ 1 ]:
                rows.append( current )
            flush_table()
            in_table = False
        elif line.startswith( "|-" ):
            if current and current[ 1 ]:
                rows.append( current )
            current = None
        elif line.startswith( "|+" ):
            continue                                   # table caption, don't need it
        elif line.startswith( "!" ):
            current = current or ( "header", [] )
            current[ 1 ].extend( _split_cells( line, "!" ) )
        elif line.startswith( "|" ):
            current = current or ( "data", [] )
            current[ 1 ].extend( _split_cells( line, "|" ) )
        elif current and current[ 1 ]:
            current[ 1 ][ -1 ] += " " + line                # cell text spilled onto the next line

    return page
