"""Takes one AJ Item Worth Wiki page (the raw wikitext) and turns it into neat rows.

Worth pages are basically wiki tables that look like this:

    header row   ! Black & Red/Default ! Orange ! ...   -> variant names
    image row    | [[File:Beard1.png]]  | ...           -> variant pictures
    value row    | A Few [[Obtainable RIMs|RIMs]] | ... -> worth labels
    (maybe more) | 60-65 Diamonds | ...                 -> diamond prices, quality, etc.

Sometimes one table repeats that header/image/value pattern a bunch of times, and
some pages have several tables under different headings ("Other Variants",
"Den Items", ...). table_groups() reads all of that into groups (one per header
row), and parse_page() picks the worth out of each group.
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
BR_RE = re.compile( r"<br\s*/?>", re.IGNORECASE )
TAG_RE = re.compile( r"</?[a-zA-Z][^>]*>" )


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


@dataclass
class Group:
    """One header row and everything under it, until the next header row."""
    section: str                       # heading path, like "Land Adventures / Normal Mode Rewards"
    headers: list[ str ]               # cleaned column names
    images: list[ str | None ]         # picture file per column (None if there isn't one)
    before_pics: list[ list[ str ] ]   # text rows above the pictures (descriptions etc.)
    after_pics: list[ list[ str ] ]    # text rows below the pictures, already cleaned
    seen_pics: bool = False            # have we passed the picture row yet?

    @property
    def text_rows( self ) -> list[ list[ str ] ]:
        return self.before_pics + self.after_pics

    @property
    def worth_row( self ) -> list[ str ] | None:
        """The worth is the first text row right after the pictures
        (or just the first text row if there are no pictures)."""
        rows = self.after_pics or self.before_pics
        return rows[ 0 ] if rows else None


def clean( text: str ) -> str:
    """Wikitext -> plain text. [[A|B]] becomes B, and files, bold, html tags, weird spaces get cleaned out."""
    text = BR_RE.sub( " ", text )                    # <br> means a line break, so keep a space there
    plain = mwparserfromhell.parse( text ).strip_code( normalize=True, collapse=True )
    plain = TAG_RE.sub( " ", plain )                 # leftover tags like <center> that strip_code keeps
    plain = plain.replace( " ", " " )          #   = the wiki's sneaky non-breaking space
    return re.sub( r"\s+", " ", plain ).strip()


def _split_cells( line: str, sep: str ) -> list[ str ]:
    """Splits '! a !! b' or '| a || b' into its cells (and drops any style stuff in front)."""
    body = line[ 1: ]
    parts = body.split( sep * 2 )
    cells = []
    for part in parts:
        # Some cells start with style stuff like `style="..." |content`, and empty
        # placeholder cells look like `| |`. The first | is a divider if what's
        # before it is style stuff (has an '=') or nothing at all, as long as
        # it isn't the | inside a [[link|label]].
        depth, cut = 0, None
        for i, ch in enumerate( part ):
            if part.startswith( "[[", i ):
                depth += 1
            elif part.startswith( "]]", i ):
                depth -= 1
            elif ch == "|" and depth == 0:
                cut = i
                break
        if cut is not None and ( "=" in part[ :cut ] or not part[ :cut ].strip() ):
            part = part[ cut + 1: ]
        cells.append( part.strip() )
    return cells


def _parse_date( raw: str ) -> str | None:
    try:
        return datetime.strptime( raw, "%B %d, %Y" ).date().isoformat()
    except ValueError:
        return None


def _raw_tables( wikitext: str ):
    """Yields ( section, rows ) per table, where rows are ( kind, raw cells )."""
    headings: dict[ int, str ] = {}   # heading level -> its text, so nested headings stack up
    section = ""
    in_table = False
    rows: list[ tuple[ str, list[ str ] ] ] = []
    current: tuple[ str, list[ str ] ] | None = None

    for raw_line in wikitext.splitlines():
        line = raw_line.strip()
        if not in_table:
            h = HEADING_RE.match( line )
            if h:
                # "==Land Adventures==" then "===Return of the Phantoms===" then
                # "====Normal Mode Rewards====" becomes one path, so two adventures
                # that both have "Normal Mode Rewards" don't overwrite each other
                level = len( h.group( 1 ) )
                headings = { lv: txt for lv, txt in headings.items() if lv < level }
                headings[ level ] = clean( h.group( 2 ) )
                section = " / ".join( headings[ lv ] for lv in sorted( headings ) )
            if line.startswith( "{|" ):
                in_table, rows, current = True, [], None
            continue

        if line.startswith( "|}" ):
            if current and current[ 1 ]:
                rows.append( current )
            yield section, rows
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


def table_groups( wikitext: str ) -> list[ Group ]:
    """Every header group on the page, with pictures and text rows sorted out."""
    groups: list[ Group ] = []
    for section, rows in _raw_tables( wikitext ):
        current: Group | None = None
        for kind, cells in rows:
            if kind == "header":
                headers = [ clean( c ) for c in cells ]
                current = Group( section, headers, [ None ] * len( headers ), [], [] )
                groups.append( current )
                continue
            if current is None:
                continue
            files = [ FILE_RE.search( c ) for c in cells ]
            if cells and all( files ):
                current.images = [ f.group( 1 ).strip() for f in files ]
                current.seen_pics = True
                continue
            cleaned = [ clean( c ) for c in cells ]
            if not any( cleaned ):
                current.seen_pics = True    # an empty row where pictures used to be counts as the picture row
                continue
            ( current.after_pics if current.seen_pics else current.before_pics ).append( cleaned )
    return groups


def parse_page( title: str, wikitext: str ) -> ItemPage:
    m = LAST_UPDATED_RE.search( wikitext )
    page = ItemPage(
        title=title,
        last_updated=_parse_date( m.group( 1 ) ) if m else None,
        categories=[ c.strip() for c in CATEGORY_RE.findall( wikitext ) ],
    )

    for g in table_groups( wikitext ):
        row = g.worth_row
        if row is None:
            continue
        for i, worth in enumerate( row[ : len( g.headers ) ] ):
            if not worth or not g.headers[ i ]:
                continue
            page.variants.append( Variant(
                item=title,
                variant=g.headers[ i ],
                section=g.section,
                worth_raw=worth,
                image=g.images[ i ] if i < len( g.images ) else None,
            ) )

    # Safety net: if two values still end up with the same name, number them
    # instead of letting the database quietly throw one away
    seen: dict[ tuple[ str, str ], int ] = {}
    for v in page.variants:
        key = ( v.section, v.variant )
        seen[ key ] = seen.get( key, 0 ) + 1
        if seen[ key ] > 1:
            v.variant = f"{v.variant} ({seen[ key ]})"

    return page
