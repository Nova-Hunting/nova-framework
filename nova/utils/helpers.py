"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Text preprocessing utilities for pattern matching
"""

import unicodedata

# Comprehensive homoglyph mapping for common Unicode spoofing attacks
# Maps visually similar characters from other scripts to ASCII equivalents
CONFUSABLES = {
    # Cyrillic lowercase -> Latin
    'а': 'a',  # U+0430 CYRILLIC SMALL LETTER A
    'е': 'e',  # U+0435 CYRILLIC SMALL LETTER IE
    'о': 'o',  # U+043E CYRILLIC SMALL LETTER O
    'р': 'p',  # U+0440 CYRILLIC SMALL LETTER ER
    'с': 'c',  # U+0441 CYRILLIC SMALL LETTER ES
    'х': 'x',  # U+0445 CYRILLIC SMALL LETTER HA
    'у': 'y',  # U+0443 CYRILLIC SMALL LETTER U
    'і': 'i',  # U+0456 CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I
    'ј': 'j',  # U+0458 CYRILLIC SMALL LETTER JE
    'ѕ': 's',  # U+0455 CYRILLIC SMALL LETTER DZE
    'һ': 'h',  # U+04BB CYRILLIC SMALL LETTER SHHA
    'ԁ': 'd',  # U+0501 CYRILLIC SMALL LETTER KOMI DE
    'ɡ': 'g',  # U+0261 LATIN SMALL LETTER SCRIPT G
    'ν': 'v',  # U+03BD GREEK SMALL LETTER NU

    # Cyrillic uppercase -> Latin
    'А': 'A',  # U+0410 CYRILLIC CAPITAL LETTER A
    'Е': 'E',  # U+0415 CYRILLIC CAPITAL LETTER IE
    'О': 'O',  # U+041E CYRILLIC CAPITAL LETTER O
    'Р': 'P',  # U+0420 CYRILLIC CAPITAL LETTER ER
    'С': 'C',  # U+0421 CYRILLIC CAPITAL LETTER ES
    'Т': 'T',  # U+0422 CYRILLIC CAPITAL LETTER TE
    'Х': 'X',  # U+0425 CYRILLIC CAPITAL LETTER HA
    'У': 'Y',  # U+0423 CYRILLIC CAPITAL LETTER U
    'М': 'M',  # U+041C CYRILLIC CAPITAL LETTER EM
    'Н': 'H',  # U+041D CYRILLIC CAPITAL LETTER EN
    'В': 'B',  # U+0412 CYRILLIC CAPITAL LETTER VE
    'К': 'K',  # U+041A CYRILLIC CAPITAL LETTER KA
    'І': 'I',  # U+0406 CYRILLIC CAPITAL LETTER BYELORUSSIAN-UKRAINIAN I

    # Greek -> Latin
    'Α': 'A',  # U+0391 GREEK CAPITAL LETTER ALPHA
    'Β': 'B',  # U+0392 GREEK CAPITAL LETTER BETA
    'Ε': 'E',  # U+0395 GREEK CAPITAL LETTER EPSILON
    'Η': 'H',  # U+0397 GREEK CAPITAL LETTER ETA
    'Ι': 'I',  # U+0399 GREEK CAPITAL LETTER IOTA
    'Κ': 'K',  # U+039A GREEK CAPITAL LETTER KAPPA
    'Μ': 'M',  # U+039C GREEK CAPITAL LETTER MU
    'Ν': 'N',  # U+039D GREEK CAPITAL LETTER NU
    'Ο': 'O',  # U+039F GREEK CAPITAL LETTER OMICRON
    'Ρ': 'P',  # U+03A1 GREEK CAPITAL LETTER RHO
    'Τ': 'T',  # U+03A4 GREEK CAPITAL LETTER TAU
    'Υ': 'Y',  # U+03A5 GREEK CAPITAL LETTER UPSILON
    'Χ': 'X',  # U+03A7 GREEK CAPITAL LETTER CHI
    'Ζ': 'Z',  # U+0396 GREEK CAPITAL LETTER ZETA
    'ο': 'o',  # U+03BF GREEK SMALL LETTER OMICRON
    'α': 'a',  # U+03B1 GREEK SMALL LETTER ALPHA (sometimes looks like 'a')

    # Zero-width characters (remove completely)
    '\u200b': '',  # ZERO WIDTH SPACE
    '\u200c': '',  # ZERO WIDTH NON-JOINER
    '\u200d': '',  # ZERO WIDTH JOINER
    '\u200e': '',  # LEFT-TO-RIGHT MARK
    '\u200f': '',  # RIGHT-TO-LEFT MARK
    '\ufeff': '',  # ZERO WIDTH NO-BREAK SPACE (BOM)
    '\u00ad': '',  # SOFT HYPHEN
    '\u2060': '',  # WORD JOINER
    '\u2061': '',  # FUNCTION APPLICATION
    '\u2062': '',  # INVISIBLE TIMES
    '\u2063': '',  # INVISIBLE SEPARATOR
    '\u2064': '',  # INVISIBLE PLUS

    # Common lookalikes
    'ℓ': 'l',  # U+2113 SCRIPT SMALL L
    'ℬ': 'B',  # U+212C SCRIPT CAPITAL B
    'ℰ': 'E',  # U+2130 SCRIPT CAPITAL E
    'ℱ': 'F',  # U+2131 SCRIPT CAPITAL F
    'ℳ': 'M',  # U+2133 SCRIPT CAPITAL M
    'ℛ': 'R',  # U+211B SCRIPT CAPITAL R
    '℮': 'e',  # U+212E ESTIMATED SYMBOL
    'ⅰ': 'i',  # U+2170 SMALL ROMAN NUMERAL ONE
    'ⅱ': 'ii', # U+2171 SMALL ROMAN NUMERAL TWO
    '‐': '-',  # U+2010 HYPHEN
    '‑': '-',  # U+2011 NON-BREAKING HYPHEN
    '‒': '-',  # U+2012 FIGURE DASH
    '–': '-',  # U+2013 EN DASH
    '—': '-',  # U+2014 EM DASH
    '―': '-',  # U+2015 HORIZONTAL BAR
}


def normalize_unicode(text: str, form: str = 'NFKC',
                      handle_confusables: bool = True) -> str:
    """
    Normalize Unicode text for consistent pattern matching.

    Applies NFKC normalization and optionally replaces visually similar
    characters (confusables) with their ASCII equivalents to prevent
    homoglyph-based evasion attacks.

    Args:
        text: The text to normalize
        form: Unicode normalization form ('NFC', 'NFKC', 'NFD', 'NFKD')
              Default: NFKC (most aggressive, recommended for security)
        handle_confusables: Whether to replace confusable characters
              Default: True (recommended for security)

    Returns:
        Normalized text string

    Example:
        >>> normalize_unicode("іgnore")  # Cyrillic 'і'
        'ignore'
        >>> normalize_unicode("ig\u200bnore")  # Zero-width space
        'ignore'
    """
    if not isinstance(text, str):
        return text

    if not text:
        return text

    # Step 1: Apply Unicode normalization (NFKC by default)
    # NFKC = Compatibility Decomposition + Canonical Composition
    # Handles: ligatures (ﬁ→fi), compatibility chars (½→1/2), etc.
    text = unicodedata.normalize(form, text)

    # Step 2: Replace confusable characters with ASCII equivalents
    if handle_confusables:
        result = []
        for char in text:
            result.append(CONFUSABLES.get(char, char))
        text = ''.join(result)

    return text


def remove_zero_width_chars(text: str) -> str:
    """
    Remove all zero-width and invisible Unicode characters from text.

    This is a lighter-weight alternative to full confusable handling
    when you only need to remove invisible characters.

    Args:
        text: The text to clean

    Returns:
        Text with zero-width characters removed
    """
    if not isinstance(text, str):
        return text

    # Zero-width and invisible characters to remove
    zero_width = {
        '\u200b', '\u200c', '\u200d', '\u200e', '\u200f',
        '\ufeff', '\u00ad', '\u2060', '\u2061', '\u2062',
        '\u2063', '\u2064'
    }

    return ''.join(c for c in text if c not in zero_width)
