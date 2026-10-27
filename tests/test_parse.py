from pathlib import Path

from ajworth.parse import parse_page

FIXTURES = Path( __file__ ).parent / "fixtures"


def test_beard_real_page():
    page = parse_page( "Beard", ( FIXTURES / "beard.wikitext" ).read_text() )
    assert page.last_updated == "2026-09-19"
    assert "Steady Value" in page.categories
    assert len( page.variants ) == 11

    first = page.variants[ 0 ]
    assert ( first.variant, first.worth_raw, first.image ) == (
        "Black & Red/Default", "A Few RIMs", "Beard1.png" )

    other = { v.variant: v for v in page.variants if v.section == "Other Variants" }
    assert other[ "Leap Year" ].worth_raw == "Good Short Collar"
    assert other[ "Rare Item Monday" ].worth_raw == "1 RIM"
    assert other[ "Luminous" ].worth_raw == "5-10 Diamonds"


def test_repeated_groups_inline_cells_and_sections():
    # A den item style page: two header/image/value groups in ONE table,
    # cells written on one line with !! and ||, plus a second section
    text = """'''Last Updated June 26, 2025'''
==Den Items==
{| class="article-table"
|-
! School Calculator !! Box of Pencils
|-
| [[File:School Calculator.png|thumb]] || [[File:Box of pencils.png|thumb]]
|-
| A Few [[Clothing Betas]] - 1 [[Den Betas|Den Beta]] || A Few [[Obtainable RIMs|RIMs]]
|-
! Schoolroom Sink
|-
| [[File:Schoolroom sink.png|thumb]]
|-
| Currently in stores
|}
==Schoolroom Easel==
{|
! Apple/Default
|-
| [[File:Schoolroom easel.png]]
|-
| A Few [[Clothing Betas]] - 1 [[Den Betas|Den Beta]]
|}
"""
    page = parse_page( "Study Group Collection", text )
    rows = [ ( v.section, v.variant, v.worth_raw, v.image ) for v in page.variants ]
    assert rows == [
        ( "Den Items", "School Calculator", "A Few Clothing Betas - 1 Den Beta", "School Calculator.png" ),
        ( "Den Items", "Box of Pencils", "A Few RIMs", "Box of pencils.png" ),
        ( "Den Items", "Schoolroom Sink", "Currently in stores", "Schoolroom sink.png" ),
        ( "Schoolroom Easel", "Apple/Default", "A Few Clothing Betas - 1 Den Beta", "Schoolroom easel.png" ),
    ]
    assert page.last_updated == "2025-06-26"


def test_page_without_tables():
    page = parse_page( "Some Article", "Just prose, no worth table.\n[[Category:Other Pages]]" )
    assert page.variants == []
    assert page.last_updated is None
    assert page.categories == [ "Other Pages" ]
