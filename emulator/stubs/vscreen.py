import math
import sys

# ── JS bridge state (set by _init_js) ─────────────────────────────────────────
_post = None         # worker postMessage(json) function

# SharedArrayBuffer-backed keyboard queue (single-producer / single-consumer).
# META[0]=head (bytes written by main thread), META[1]=tail (bytes read by us),
# META[2]=stop flag (set by main thread Stop button).
_meta = None         # Int32Array control words
_data = None         # Uint8Array byte ring
_cap = 0
_kstate = None       # Uint8Array key-state table (HID usage code -> 0/1)
_Atomics = None

CANVAS_W = 400
CANVAS_H = 240

# Drawing command batch — flushed to main thread each frame.
_batch = []

# Set by _runner before main()
_blocking_read = None
_registered_callback = None
_in_callback = False


class StopApp(Exception):
  """Raised to unwind the app when the user presses Stop."""


def _init_js():
  global _post, _meta, _data, _cap, _kstate, _Atomics, _batch
  import json
  from js import (emulator_post_raw, emulator_meta, emulator_data,
                  emulator_kstate, Atomics)
  _post = lambda d: emulator_post_raw(json.dumps(d))
  _meta = emulator_meta
  _data = emulator_data
  _cap = int(emulator_data.length)
  _kstate = emulator_kstate
  _Atomics = Atomics
  _batch = []


# ── Input helpers (SAB) ───────────────────────────────────────────────────────

def _read_available(n):
  head = int(_Atomics.load(_meta, 0))
  tail = int(_Atomics.load(_meta, 1))
  if tail >= head:
    return ''
  out = bytearray()
  while tail < head and len(out) < n:
    out.append(int(_data[tail % _cap]))
    tail += 1
  _Atomics.store(_meta, 1, tail)
  return bytes(out).decode('utf-8', 'replace')


def _has_input():
  return int(_Atomics.load(_meta, 0)) > int(_Atomics.load(_meta, 1))


def _stop_requested():
  return int(_Atomics.load(_meta, 2)) != 0


def _wait_input(timeout_ms):
  """Park up to timeout_ms; wakes early when a key arrives or Stop is set."""
  head = int(_Atomics.load(_meta, 0))
  if int(_meta[1]) >= head:
    _Atomics.wait(_meta, 0, head, max(1, int(timeout_ms)))


# ── Draw-command batch ────────────────────────────────────────────────────────

def _flush_frame():
  _post({'type': 'frame', 'cmds': list(_batch)})
  _batch.clear()


_FONT_MAP = {
  'u8g2_font_profont11_mf':     '9px "Courier New",monospace',
  'u8g2_font_profont15_mf':     '12px "Courier New",monospace',
  'u8g2_font_profont22_mf':     '18px "Courier New",monospace',
  'u8g2_font_profont29_mf':     '24px "Courier New",monospace',
  'u8g2_font_tenfatguys_tf':    'bold 11px "Courier New",monospace',
  'u8g2_font_tenthinnerguys_tf':'9px "Courier New",monospace',
  'u8g2_font_t0_11_me':         '9px monospace',
  'u8g2_font_t0_15_me':         '12px monospace',
  'u8g2_font_t0_15b_me':        'bold 12px monospace',
  'u8g2_font_t0_17_me':         '14px monospace',
  'u8g2_font_t0_22_me':         '18px monospace',
  'spleen612':                  '10px monospace',
  'spleen816':                  '14px monospace',
}


class Vscreen:
  def __init__(self):
    self._draw_color = 1     # 0=black, 1=white, 2=xor
    self._font = '12px "Courier New",monospace'
    self._font_px_cache = 12
    self._baseline = 'alphabetic'   # u8g2 default reference is the baseline
    self._dither = 16
    self._callback = None
    self._active = True

  @property
  def active(self):
    return self._active

  def _emit(self, *cmd):
    _batch.append(list(cmd))

  # ── state ──
  def set_draw_color(self, color):
    self._draw_color = color
    self._emit('col', color)

  def set_dither(self, level):
    self._dither = max(0, min(16, int(level)))
    self._emit('dith', self._dither)

  def set_font(self, font_name):
    self._font = _FONT_MAP.get(str(font_name), '12px "Courier New",monospace')
    try:
      self._font_px_cache = int(self._font.split('px')[0].split()[-1])
    except Exception:
      self._font_px_cache = 12
    self._emit('font', self._font)

  def set_font_mode(self, mode): pass
  def set_font_direction(self, d): pass
  def set_bitmap_mode(self, mode): pass
  def set_font_pos_baseline(self): self._baseline = 'alphabetic'; self._emit('base', 'alphabetic')
  def set_font_pos_top(self):      self._baseline = 'top';        self._emit('base', 'top')
  def set_font_pos_bottom(self):   self._baseline = 'bottom';     self._emit('base', 'bottom')
  def set_font_pos_center(self):   self._baseline = 'middle';     self._emit('base', 'middle')
  def set_terminal_font(self, *a): pass
  def set_terminal_font_size(self, size): pass

  # ── primitives ──
  def draw_pixel(self, x, y):              self._emit('box', x, y, 1, 1)
  def draw_line(self, x1, y1, x2, y2):     self._emit('line', x1, y1, x2, y2)
  def draw_h_line(self, x, y, w):          self._emit('box', x, y, w, 1)
  def draw_v_line(self, x, y, h):          self._emit('box', x, y, 1, h)
  def draw_box(self, x, y, w, h):          self._emit('box', x, y, w, h)
  def draw_frame(self, x, y, w, h):        self._emit('frame', x, y, w, h)
  def draw_rbox(self, x, y, w, h, r):      self._emit('rbox', x, y, w, h, r)
  def draw_rframe(self, x, y, w, h, r):    self._emit('rframe', x, y, w, h, r)
  def draw_circle(self, x, y, r, opt=0):   self._emit('circ', x, y, r)
  def draw_disc(self, x, y, r, opt=0):     self._emit('disc', x, y, r)
  def draw_arc(self, x, y, rad, s, e):     self._emit('arc', x, y, rad, s, e)
  def draw_triangle(self, x0, y0, x1, y1, x2, y2):
    self._emit('tri', x0, y0, x1, y1, x2, y2)
  def draw_ellipse(self, x, y, rx, ry, opt=0):        self._emit('ell', x, y, rx, ry, 0)
  def draw_filled_ellipse(self, x, y, rx, ry, opt=0): self._emit('ell', x, y, rx, ry, 1)

  def draw_polygon(self, pts):
    self._emit('poly', list(pts))

  def draw_str(self, x, y, text):
    self._emit('str', x, y, str(text))

  def draw_utf8(self, x, y, text):
    self._emit('str', x, y, str(text))

  def draw_utf8_v(self, x, y, text):
    self._emit('vstr', x, y, str(text))

  def draw_button_utf8(self, x, y, flags, width, ph, pv, text):
    tw = self.get_str_width(text)
    w = width if width > 0 else tw + 2 * ph
    self._emit('frame', x, y, w, self._font_px_cache + 2 * pv)
    self._emit('str', x + ph, y + pv, str(text))

  def get_str_width(self, text):
    # Monospace approximation: char width ≈ 0.6 × font px
    return int(len(str(text)) * self._font_px_cache * 0.6)

  def get_utf8_width(self, text):
    return self.get_str_width(text)

  # ── images ──
  def draw_image(self, x, y, image, frame=0):
    if not image:
      return
    _, w, h, data, _ = image
    self._emit_xbm(x, y, w, h, data, frame)

  def draw_xbm(self, x, y, w, h, data):
    self._emit_xbm(x, y, w, h, data, 0)

  def draw_xbm_t(self, x, y, w, h, data):
    self._emit_xbm(x, y, w, h, data, 0)

  def _emit_xbm(self, x, y, w, h, data, frame):
    # Pack the visible frame's bytes into a plain list (MSB-first) for the renderer.
    stride = (w + 7) // 8
    off = frame * stride * h
    chunk = bytes(data[off:off + stride * h])
    self._emit('xbm', x, y, w, h, list(chunk))

  def draw_3d_faces(self, points, indices, dither):
    faces = []
    for i, idx in enumerate(indices):
      d = dither[i]
      if d < 0:
        continue
      b = idx * 6
      faces.append([d, points[b], points[b+1], points[b+2],
                       points[b+3], points[b+4], points[b+5]])
    self._emit('faces', faces)

  draw_2d_faces = draw_3d_faces

  def draw_polygon_texture(self, pts, map_arr, image_tuple, frame=0):
    self._emit('poly', list(pts))

  def capture_as_xbm(self, x, y, w, h, buf): pass

  # ── buffers (no-ops; renderer clears each frame) ──
  def clear_buffer(self): pass
  def switch_buffer(self, n): pass
  def copy_buffer(self, to_, from_): pass

  # ── terminal / input ──
  def print(self, text):
    if isinstance(text, (bytes, bytearray)):
      text = text.decode('utf-8', 'replace')
    _post({'type': 'terminal', 'data': str(text)})

  def send_char(self, data):
    ch = data.decode('utf-8', 'replace') if isinstance(data, (bytes, bytearray)) else str(data)
    from js import emulator_push_key
    emulator_push_key(ch)

  def send_key_event(self, key, modifier, event_type): pass

  def read_nb(self, max_len):
    s = _read_available(max_len)
    return (len(s.encode()), s)

  def poll(self):
    return _has_input()

  def get_key_state(self, key_code):
    return int(_kstate[int(key_code) & 0xFF])

  def get_tp_keys(self):
    # tp[0] = slider analog position (0..40, 0xff = not touched), published by the
    # on-screen slider via kMeta[3]. Remaining bytes (touch/buttons) are unused here.
    tp = bytearray(7)
    pos = int(_Atomics.load(_meta, 3)) & 0xFF
    tp[0] = pos
    return bytes(tp)

  def get_terminal_size(self):
    # Matches displayapi.c font_size 0: 8×16 cell → 50×15 on the 400×240 screen.
    return (CANVAS_W // 8, CANVAS_H // 16)

  @property
  def suspend_inactive_screen(self): return False
  @suspend_inactive_screen.setter
  def suspend_inactive_screen(self, v): pass

  # ── callback ──
  def callback(self, fn):
    global _registered_callback
    _registered_callback = fn
    self._callback = fn
    _post({'type': 'mode', 'graphics': fn is not None})

  def callback_exists(self):
    return self._callback is not None

  def unsubscribe_callback(self):
    self.callback(None)

  def finished(self):
    # Presentation is driven once per frame by the runner; nothing to do here.
    pass


class VscreenStream:
  def __init__(self, v=None):
    self.v = v or Vscreen()

  def write(self, s):
    self.v.print(s)

  def read(self, n=1, wait=7):
    if _blocking_read is not None:
      return _blocking_read(n, wait)
    while not _has_input():
      if _stop_requested():
        raise StopApp()
      _wait_input(wait)
    return _read_available(n)

  def poll(self):
    return self.v.poll()

  def async_read(self, n=1, wait=20):
    return self.read(n, wait)

  def ioctl(self, op, arg):
    return 0

  def register_module(self, obj): pass

  def __enter__(self): return self
  def __exit__(self, *a): pass
