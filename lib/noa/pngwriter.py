# Minimal 1-bit grayscale PNG encoder for Pocket Deck screen captures.
#
# capture_as_xbm() gives an XBM buffer (1 bit/pixel, LSB-first, bit set =
# foreground). OpenAI vision needs PNG/JPEG, so this packs that buffer into a
# 1-bit grayscale PNG. Captures are occasional, so a plain-Python encoder is
# fine.
#
# The firmware's `deflate` module is decompression-only (no compress/.write),
# so PNG's zlib-wrapped IDAT is emitted as *uncompressed* DEFLATE stored blocks
# built by hand. The image is already 1bpp (~12 KB for 400x240), so the lack of
# compression is acceptable for an occasional screenshot.
#
# The three hot byte-loops (row pack/invert, CRC32, Adler32) are @micropython.viper
# so an occasional capture stays fast; the emitted PNG bytes are unchanged.

import array

_PNG_SIG = b'\x89PNG\r\n\x1a\n'

# ── CRC32 (don't assume binascii.crc32 exists in the firmware) ───────────────
_crc_table = None

def _make_crc_table():
  table = []
  for n in range(256):
    c = n
    for _ in range(8):
      c = (0xEDB88320 ^ (c >> 1)) if (c & 1) else (c >> 1)
    table.append(c & 0xFFFFFFFF)
  return table

@micropython.viper
def _crc32_v(data: ptr8, n: int, crc: uint, table: ptr32) -> uint:
  # crc stays a uint so `c >> 8` is a logical (non-sign-extending) shift.
  c = crc
  i = 0
  while i < n:
    idx = (int(c) ^ int(data[i])) & 0xFF
    c = uint(table[idx]) ^ (c >> 8)
    i += 1
  return c

def _crc32(data, crc):
  global _crc_table
  if _crc_table is None:
    _crc_table = array.array('I', _make_crc_table())
  if len(data) == 0:
    return crc & 0xFFFFFFFF
  return int(_crc32_v(data, len(data), crc, _crc_table)) & 0xFFFFFFFF

@micropython.viper
def _adler_v(data: ptr8, n: int, out: ptr32):
  # Reduce every byte so both accumulators stay < 65521 (small-int range).
  a = 1
  b = 0
  i = 0
  while i < n:
    a += int(data[i])
    if a >= 65521:
      a -= 65521
    b += a
    if b >= 65521:
      b -= 65521
    i += 1
  out[0] = a
  out[1] = b

def _adler32_ab(data):
  # Returns the Adler-32 halves (a = low 16, b = high 16), each < 65521.
  out = array.array('I', (0, 0))
  _adler_v(data, len(data), out)
  return out[0], out[1]

# Explicit byte packing — avoid int.to_bytes(), whose byteorder handling has
# varied across MicroPython versions (a malformed length/CRC silently produces
# an undecodable PNG).
def _be32(v):
  return bytes([(v >> 24) & 0xff, (v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff])

def _le16(v):
  return bytes([v & 0xff, (v >> 8) & 0xff])

def _zlib_stored(raw):
  # zlib header (CMF=0x78, FLG=0x01) + DEFLATE stored blocks + Adler-32.
  out = bytearray(b'\x78\x01')
  n = len(raw)
  if n == 0:
    out += bytes([0x01, 0x00, 0x00, 0xff, 0xff])
  else:
    pos = 0
    while pos < n:
      chunk = min(65535, n - pos)
      final = 1 if (pos + chunk) >= n else 0  # BFINAL in bit0, BTYPE=00
      out.append(final)
      out += _le16(chunk)              # LEN
      out += _le16(chunk ^ 0xFFFF)     # NLEN (~LEN)
      out += raw[pos:pos + chunk]
      pos += chunk
  a, b = _adler32_ab(raw)
  # Adler-32 = (b << 16) | a, big-endian. Emit straight from the 16-bit halves
  # so no 32-bit intermediate is ever formed.
  out += bytes([(b >> 8) & 0xff, b & 0xff, (a >> 8) & 0xff, a & 0xff])
  return bytes(out)

def _chunk(tag, data):
  out = bytearray()
  out += _be32(len(data))
  out += tag
  out += data
  crc = _crc32(tag, 0xFFFFFFFF)
  crc = _crc32(data, crc) ^ 0xFFFFFFFF
  out += _be32(crc & 0xFFFFFFFF)
  return bytes(out)

# ── Row packing ──────────────────────────────────────────────────────────────
# The device's capture buffer is MSB-first (pixel 0 = bit 7), the same bit order
# PNG 1-bit grayscale uses, so NO bit reversal is needed — a reversal mirrors
# the image within every byte. `invert` flips polarity so drawn pixels (buffer
# bit=1) render black on white, which is the most legible for the model. Each
# PNG row is prefixed with a filter-type byte (0 = none).
@micropython.viper
def _pack_rows(dst: ptr8, src: ptr8, stride: int, h: int, invert: int):
  s = 0
  d = 0
  y = 0
  while y < h:
    dst[d] = 0  # filter type 0 (none)
    d += 1
    x = 0
    if invert:
      while x < stride:
        dst[d] = src[s] ^ 0xFF
        d += 1
        s += 1
        x += 1
    else:
      while x < stride:
        dst[d] = src[s]
        d += 1
        s += 1
        x += 1
    y += 1

def encode_mono_xbm(buf, w, h, invert=True):
  """Encode a 1bpp MSB-first buffer into 1-bit grayscale PNG bytes."""
  stride = (w + 7) // 8
  rows = bytearray(h * (stride + 1))
  _pack_rows(rows, buf, stride, h, 1 if invert else 0)

  idat = _zlib_stored(rows)

  ihdr = bytearray()
  ihdr += _be32(w)
  ihdr += _be32(h)
  # bit depth 1, color type 0 (grayscale), compression 0, filter 0, interlace 0
  ihdr += bytes([1, 0, 0, 0, 0])

  return _PNG_SIG + _chunk(b'IHDR', bytes(ihdr)) + _chunk(b'IDAT', idat) + _chunk(b'IEND', b'')
