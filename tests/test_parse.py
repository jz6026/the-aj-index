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


def test_skips_description_and_location_rows():
    # Like the Alpha Set page: a description row BEFORE the pictures,
    # and like adventure pages: a chest location row AFTER the values
    text = """{|
! Alpha Sword !! Alpha Helmet
|-
| Redeemed from 96 unique Adopt-A-Pets || Redeemed from 150 unique Adopt-A-Pets
|-
| [[File:Alpha Sword1.png|thumb]] || [[File:Alphahelm.png|thumb]]
|-
| 30 Black [[Rare Long Spiked Collar|Long Collars]] || 10 Black [[Rare Long Spiked Collar|Long Collars]]
|-
| Top Left Chest || Top Right Chest
|}
"""
    page = parse_page( "Alpha Set", text )
    assert [ ( v.variant, v.worth_raw, v.image ) for v in page.variants ] == [
        ( "Alpha Sword", "30 Black Long Collars", "Alpha Sword1.png" ),
        ( "Alpha Helmet", "10 Black Long Collars", "Alphahelm.png" ),
    ]


def test_nested_headings_keep_repeated_sections_apart():
    # Two adventures both have a "Normal Mode Rewards" section with the same column name
    table = "{|\n! Bunny Fence\n|-\n| [[File:a.png]]\n|-\n| %s\n|}\n"
    text = ( "==Land Adventures==\n===Return of the Phantoms===\n====Normal Mode Rewards====\n"
             + table % "A Few RIMs"
             + "===The Phantom Portal===\n====Normal Mode Rewards====\n"
             + table % "2-5 Diamonds" )
    page = parse_page( "Adventure Rewards", text )
    assert [ ( v.section, v.worth_raw ) for v in page.variants ] == [
        ( "Land Adventures / Return of the Phantoms / Normal Mode Rewards", "A Few RIMs" ),
        ( "Land Adventures / The Phantom Portal / Normal Mode Rewards", "2-5 Diamonds" ),
    ]


def test_true_duplicates_get_numbered_not_dropped():
    text = "{|\n! Blue & Pink !! Blue & Pink\n|-\n| A Few RIMs || 1 RIM\n|}\n"
    page = parse_page( "Brigade Armor", text )
    assert [ v.variant for v in page.variants ] == [ "Blue & Pink", "Blue & Pink (2)" ]


def test_page_without_tables():
    page = parse_page( "Some Article", "Just prose, no worth table.\n[[Category:Other Pages]]" )
    assert page.variants == []
    assert page.last_updated is None
    assert page.categories == [ "Other Pages" ]


def test_header_cells_styled_as_normal_cells():
    """Cupid Wings: the Glossy + Non-Glossy tables use | cells (styled bold) for the colors."""
    page = parse_page( "Cupid Wings", ( FIXTURES / "cupid_wings.wikitext" ).read_text() )
    by_section = {}
    for v in page.variants:
        by_section.setdefault( v.section, {} )[ v.variant ] = v.worth_raw
    assert by_section[ "Glossy Cupid Wings" ][ "Tan" ] == "25 Black Long Collars"
    assert by_section[ "Non-Glossy Cupid Wings" ][ "White" ] == "5-10 Diamonds"     # the one ! cell in a | row
    assert len( by_section[ "Other Variants" ] ) == 9
    assert len( page.variants ) == 24
