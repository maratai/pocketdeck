#!/usr/bin/env python3
"""
Convert a u8g2 single-font C file into the base64 JS the emulator loads.

The device's font symbols (see displayapi.c convert_font_str) are u8g2 byte
arrays declared as C string literals:

    const uint8_t u8g2_font_t0_15_me[12156] U8G2_FONT_SECTION(...) =
      "\\220\\2\\3..." "...";

We parse the concatenated string literals (octal/hex/std escapes), base64-encode
the bytes, and emit:

    window.U8G2_<UPPERCASE_SHORT_NAME> = "<base64>";

so emulator/fonts/u8g2font.js (the U8g2Font decoder) renders the exact device
glyphs in graphics mode, matching the real screen.

Usage:
    u8g2font_to_js.py <font.c> [<font.c> ...] -o <out_dir>
"""
import argparse
import base64
import os
import re
import sys

# C escape parsing: octal (\NNN, 1–3 digits), hex (\xNN), and the standard
# single-char escapes. u8g2's output uses octal heavily plus literal bytes.
_SIMPLE = {'n': 10, 't': 9, 'r': 13, 'a': 7, 'b': 8, 'f': 12, 'v': 11,
           '\\': 92, '"': 34, "'": 39, '?': 63, '0': 0}


def _unescape(s):
  out = bytearray()
  i, n = 0, len(s)
  while i < n:
    c = s[i]
    if c != '\\':
      out.append(ord(c) & 0xFF)
      i += 1
      continue
    i += 1
    if i >= n:
      break
    e = s[i]
    if e in '01234567':                 # octal, up to 3 digits
      j = i
      while j < n and j < i + 3 and s[j] in '01234567':
        j += 1
      out.append(int(s[i:j], 8) & 0xFF)
      i = j
    elif e == 'x':                      # hex, all following hex digits
      j = i + 1
      while j < n and s[j] in '0123456789abcdefABCDEF':
        j += 1
      out.append(int(s[i + 1:j], 16) & 0xFF)
      i = j
    elif e in _SIMPLE:
      out.append(_SIMPLE[e])
      i += 1
    else:                               # unknown escape → literal char
      out.append(ord(e) & 0xFF)
      i += 1
  return bytes(out)


def parse_all_fonts(text):
  """Yield (symbol_name, declared_size_or_None, font_bytes) for each font
  array declaration in the file (some files, e.g. spleen, define several)."""
  for m in re.finditer(r'\b(u8g2_font_\w+|spleen\w+)\s*\[\s*(\d*)\s*\]', text):
    yield _parse_one(text, m)


def _parse_one(text, m):
  name = m.group(1)
  declared = int(m.group(2)) if m.group(2) else None

  # Scan string literals from the '=' onward. We cannot just slice to the next
  # ';' — printable font bytes (including ';') appear *literally* inside the
  # quotes. Instead tokenize: skip whitespace, consume each "..." literal
  # (honouring \" escapes), and stop at the first non-string token (the ';').
  i = text.index('=', m.end()) + 1
  n = len(text)
  parts = []
  while i < n:
    while i < n and text[i] in ' \t\r\n':
      i += 1
    if i >= n or text[i] != '"':
      break                              # reached the terminating ';'
    i += 1                               # opening quote
    start = i
    while i < n:
      if text[i] == '\\':
        i += 2
        continue
      if text[i] == '"':
        break
      i += 1
    parts.append(text[start:i])
    i += 1                               # closing quote
  data = _unescape(''.join(parts))
  return name, declared, data


def short_name(symbol):
  # window var: drop the u8g2_font_ prefix, uppercase. (spleen* keep as-is.)
  base = symbol[len('u8g2_font_'):] if symbol.startswith('u8g2_font_') else symbol
  return 'U8G2_' + base.upper()


def convert(path, out_dir):
  with open(path, 'r', errors='replace') as fh:
    text = fh.read()
  for symbol, declared, data in parse_all_fonts(text):
    # u8g2 C arrays include a trailing NUL the data itself omits, so a parsed
    # length of declared-1 is expected and correct.
    if declared is not None and declared - len(data) not in (0, 1):
      print(f'  WARNING {symbol}: declared {declared} bytes, parsed {len(data)}',
            file=sys.stderr)
    var = short_name(symbol)
    b64 = base64.b64encode(data).decode('ascii')
    out_name = symbol[len('u8g2_font_'):] if symbol.startswith('u8g2_font_') else symbol
    out_path = os.path.join(out_dir, out_name + '.js')
    with open(out_path, 'w') as fh:
      fh.write(f'// {symbol} — extracted from the Pocket Deck firmware (u8g2).\n')
      fh.write(f'window.{var} = "{b64}";\n')
    print(f'  {symbol}: {len(data)} bytes -> {out_path}  (window.{var})')


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument('inputs', nargs='+')
  ap.add_argument('-o', '--out-dir', required=True)
  args = ap.parse_args()
  os.makedirs(args.out_dir, exist_ok=True)
  for p in args.inputs:
    convert(p, args.out_dir)


if __name__ == '__main__':
  main()
