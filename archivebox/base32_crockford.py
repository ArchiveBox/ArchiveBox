"""
base32-crockford
================

A Python module implementing the alternate base32 encoding as described
by Douglas Crockford at: http://www.crockford.com/wrmg/base32.html.

He designed the encoding to:

   * Be human and machine readable
   * Be compact
   * Be error resistant
   * Be pronounceable

It uses a symbol set of 10 digits and 22 letters, excluding I, L O and
U. Decoding is not case sensitive, and 'i' and 'l' are converted to '1'
and 'o' is converted to '0'. Encoding uses only upper-case characters.

Hyphens may be present in symbol strings to improve readability, and
are removed when decoding.

A check symbol can be appended to a symbol string to detect errors
within the string.

"""

import re
import sys

PY3 = sys.version_info[0] == 3

if not PY3:
    import string as str


__all__ = ["encode", "decode", "normalize"]


if PY3:
    string_types = str,
else:
    string_types = basestring,

# The encoded symbol space does not include I, L, O or U
symbols = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
# These five symbols are exclusively for checksum values
check_symbols = '*~$=U'

encode_symbols = dict((i, ch) for (i, ch) in enumerate(symbols + check_symbols))
decode_symbols = dict((ch, i) for (i, ch) in enumerate(symbols + check_symbols))
normalize_symbols = str.maketrans('IiLlOo', '111100')
valid_symbols = re.compile('^[%s]+[%s]?$' % (symbols,
                                             re.escape(check_symbols)))

base = len(symbols)
check_base = len(symbols + check_symbols)


def encode(number, checksum=False, split=0):
    """Encode an integer into a symbol string.

    A ValueError is raised on invalid input.

    If checksum is set to True, a check symbol will be
    calculated and appended to the string.

    If split is specified, the string will be divided into
    clusters of that size separated by hyphens.

    The encoded string is returned.
    """
    number = int(number)
    if number < 0:
        raise ValueError("number '%d' is not a positive integer" % number)

    split = int(split)
    if split < 0:
        raise ValueError("split '%d' is not a positive integer" % split)

    check_symbol = ''
    if checksum:
        check_symbol = encode_symbols[number % check_base]

    if number == 0:
        return '0' + check_symbol

    symbol_string = ''
    while number > 0:
        remainder = number % base
        number //= base
        symbol_string = encode_symbols[remainder] + symbol_string
    symbol_string = symbol_string + check_symbol

    if split:
        chunks = []
        for pos in range(0, len(symbol_string), split):
            chunks.append(symbol_string[pos:pos + split])
        symbol_string = '-'.join(chunks)

    return symbol_string


def decode(symbol_string, checksum=False, strict=False):
    """Decode an encoded symbol string.

    If checksum is set to True, the string is assumed to have a
    trailing check symbol which will be validated. If the
    checksum validation fails, a ValueError is raised.

    If strict is set to True, a ValueError is raised if the
    normalization step requires changes to the string.

    The decoded string is returned.
    """
    symbol_string = normalize(symbol_string, strict=strict)
    if checksum:
        symbol_string, check_symbol = symbol_string[:-1], symbol_string[-1]

    number = 0
    for symbol in symbol_string:
        number = number * base + decode_symbols[symbol]

    if checksum:
        check_value = decode_symbols[check_symbol]
        modulo = number % check_base
        if check_value != modulo:
            raise ValueError("invalid check symbol '%s' for string '%s'" %
                             (check_symbol, symbol_string))

    return number


def normalize(symbol_string, strict=False):
    """Normalize an encoded symbol string.

    Normalization provides error correction and prepares the
    string for decoding. These transformations are applied:

       1. Hyphens are removed
       2. 'I', 'i', 'L' or 'l' are converted to '1'
       3. 'O' or 'o' are converted to '0'
       4. All characters are converted to uppercase

    A TypeError is raised if an invalid string type is provided.

    A ValueError is raised if the normalized string contains
    invalid characters.

    If the strict parameter is set to True, a ValueError is raised
    if any of the above transformations are applied.

    The normalized string is returned.
    """
    if isinstance(symbol_string, string_types):
        if not PY3:
            try:
                symbol_string = symbol_string.encode('ascii')
            except UnicodeEncodeError:
                raise ValueError("string should only contain ASCII characters")
    else:
        raise TypeError("string is of invalid type %s" %
                        symbol_string.__class__.__name__)

    norm_string = symbol_string.replace('-', '').translate(normalize_symbols).upper()

    if not valid_symbols.match(norm_string):
        raise ValueError("string '%s' contains invalid characters" % norm_string)

    if strict and norm_string != symbol_string:
        raise ValueError("string '%s' requires normalization" % symbol_string)

    return norm_string
