import re
import struct

def read(filename):
  try:
    with open(filename, 'r') as f:
      content = f.read()
  except (OSError, FileNotFoundError):
    return (filename, 8, 8, bytes(8), 1)  # dummy 8×8 blank image
  lines = re.split(r'[\r\n]+', content)
  width = height = 0
  for line in lines:
    m = re.search(r'width\s+(\d+)', line)
    if m: width = int(m.group(1))
    m = re.search(r'height\s+(\d+)', line)
    if m: height = int(m.group(1))

  data = bytearray()
  for line in lines:
    for m in re.finditer(r'0x([0-9a-fA-F]{2})', line):
      b = int(m.group(1), 16)
      # XBM is LSB-first; reverse bits to MSB-first for our renderer
      b = int('{:08b}'.format(b)[::-1], 2)
      data.append(b)

  return (filename, width, height, bytes(data), 1)


def read_xbmr(filename):
  try:
    with open(filename, 'rb') as f:
      content = f.read()
  except (OSError, FileNotFoundError):
    return (filename, 8, 8, bytes(8), 1)
  header = struct.unpack_from('<hhhh', content, 0)
  num_frames = header[1]
  width  = header[2]
  height = header[3]
  return (filename, width, height, memoryview(content)[8:], num_frames)


def scale(image, factor):
  name, w, h, data, nf = image
  nw = w * factor
  nh = h * factor
  stride_old = (w + 7) // 8
  stride_new = (nw + 7) // 8
  out = bytearray(stride_new * nh * nf)
  for f in range(nf):
    fo = f * stride_old * h
    fn_ = f * stride_new * nh
    for row in range(nh):
      src_row = row // factor
      for col in range(nw):
        src_col = col // factor
        bi = fo + src_row * stride_old + src_col // 8
        bit = (data[bi] >> (7 - (src_col & 7))) & 1
        if bit:
          ob = fn_ + row * stride_new + col // 8
          out[ob] |= (1 << (7 - (col & 7)))
  return (name, nw, nh, bytes(out), nf)
