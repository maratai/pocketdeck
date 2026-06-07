"""
App runner — SharedArrayBuffer + Atomics for input, postMessage for rendering.

Architecture (why this works in a browser):
  * App code is synchronous and blocks in vs.read() / time.sleep().
  * The WORKER thread parks in Atomics.wait().  The MAIN thread writes
    keystrokes into a SharedArrayBuffer and calls Atomics.notify(), so the
    blocked worker wakes — no event-loop yielding required for input.
  * RENDERING happens on the MAIN thread: each frame the worker batches
    draw commands and postMessage()s them.  The main thread's event loop is
    free, so it paints and presents normally.  (A worker blocked in
    Atomics.wait cannot present an OffscreenCanvas — hence main-thread render.)
"""

import json
import sys
import time as _t

# ── MicroPython time compat ───────────────────────────────────────────────────
if not hasattr(_t, '_emulator_orig_sleep'):
  _t._emulator_orig_sleep = _t.sleep
_builtin_sleep = _t._emulator_orig_sleep

if not hasattr(_t, 'ticks_ms'):
  _t.ticks_ms   = lambda: int(_t.time() * 1000)      & 0x3FFFFFFF
  _t.ticks_us   = lambda: int(_t.time() * 1_000_000) & 0x3FFFFFFF
  _t.ticks_diff = lambda a, b: (a - b) & 0x3FFFFFFF
  _t.ticks_add  = lambda t, d: (t + d) & 0x3FFFFFFF
  _t.sleep_ms   = lambda ms: _builtin_sleep(ms / 1000)
  _t.sleep_us   = lambda us: _builtin_sleep(us / 1_000_000)

# MicroPython's time.mktime() takes an 8-tuple (year, month, mday, hour, min,
# sec, weekday, yearday) and is the UTC inverse of time.gmtime(). CPython's
# mktime() instead needs a full 9-tuple with valid wday/yday/isdst and does
# local-time conversion, so device code like analog_clock's
# `time.mktime((y, m, 1, 0,0,0, 0, 0))` raises "illegal time tuple argument".
# Replace it with calendar.timegm (true gmtime inverse, reads only the first 6
# fields) so gmtime(mktime(...)) round-trips exactly as on the device.
if getattr(_t, '_emulator_mktime_patched', None) is None:
  import calendar as _cal
  _t.mktime = lambda tup: _cal.timegm(tuple(tup))
  _t._emulator_mktime_patched = True

sys.modules.setdefault('utime', sys.modules['time'])


def _post(d):
  from js import emulator_post_raw
  emulator_post_raw(json.dumps(d))


def _install_micropython_builtins():
  # MicroPython exposes const() as a bare builtin and allows decorators like
  # @micropython.native. Provide those so unmodified device code imports cleanly.
  import builtins
  if not hasattr(builtins, 'const'):
    builtins.const = lambda x: x

  # MicroPython's bytearray accepts str in extend/+/+= (implicitly UTF-8 encoding).
  # CPython rejects str there, which breaks device code like PEM's insert_str
  # (`bytearray.extend(some_str)`). Provide a lenient bytearray to match.
  if not getattr(builtins, '_mp_bytearray_installed', False):
    _orig = bytearray

    def _enc(x):
      return x.encode('utf-8') if isinstance(x, str) else x

    class _MPBytearray(_orig):
      def extend(self, x): return _orig.extend(self, _enc(x))
      def __iadd__(self, x): _orig.extend(self, _enc(x)); return self
      def __add__(self, x): return _MPBytearray(_orig.__add__(self, _enc(x)))
      def __getitem__(self, k):
        r = _orig.__getitem__(self, k)
        return _MPBytearray(r) if isinstance(k, slice) else r

    builtins.bytearray = _MPBytearray
    builtins._mp_bytearray_installed = True

  # MicroPython lets you write str to a file opened in binary mode (it encodes
  # implicitly). CPython raises, which makes device code like PEM's save() fail
  # and spin in a "retry forever" loop. Wrap open() to accept str on binary write.
  if not getattr(builtins, '_mp_open_installed', False):
    _orig_open = builtins.open

    class _BinFile:
      def __init__(self, f): self.__dict__['_f'] = f
      def write(self, data):
        if isinstance(data, str):
          data = data.encode('utf-8')
        return self._f.write(data)
      def __getattr__(self, n): return getattr(self._f, n)
      def __setattr__(self, n, v): setattr(self._f, n, v)
      def __enter__(self): self._f.__enter__(); return self
      def __exit__(self, *a): return self._f.__exit__(*a)
      def __iter__(self): return iter(self._f)

    def _mp_open(file, mode='r', *a, **k):
      f = _orig_open(file, mode, *a, **k)
      return _BinFile(f) if 'b' in mode and ('w' in mode or 'a' in mode or '+' in mode) else f

    builtins.open = _mp_open
    builtins._mp_open_installed = True

  # os.sync() is a no-op on the in-memory FS; ensure it exists and never raises
  # (PEM calls it inside save() — a raise there would also trip the retry loop).
  import os as _os
  _os.sync = lambda: None


def run_app(code_path, args_list):
  _install_micropython_builtins()

  # Default working directory to the demo documents folder so PEM's open-file
  # dialog (os.getcwd) and relative paths land in a folder with real content.
  import os
  try:
    os.chdir('/sd/Documents')
  except Exception:
    pass

  import vscreen as vs_mod
  vs_mod._init_js()

  # Frame-rate cap. Apps drive rendering by calling delay_tick()/time.sleep() in
  # a tight loop (analog_clock spins at ~4 ms ≈ 250 fps), which is far faster and
  # busier than the real ~75 Hz LCD. Gate frame production so callbacks render at
  # most ~75 fps — matching the device and cutting postMessage volume to the main
  # thread. App logic (timers, input) is unaffected; only the redraw is throttled.
  _MIN_FRAME_S = 1.0 / 75
  _last_frame = [0.0]

  def _do_frame(force=False):
    cb = vs_mod._registered_callback
    if not cb or vs_mod._in_callback:
      return
    now = _t.time()
    if not force and (now - _last_frame[0]) < _MIN_FRAME_S:
      return
    _last_frame[0] = now
    vs_mod._batch.clear()
    vs_mod._in_callback = True
    try:
      cb(True)
    except vs_mod.StopApp:
      raise
    except Exception:
      import traceback
      _post({'type': 'error', 'message': traceback.format_exc()})
    finally:
      vs_mod._in_callback = False
    vs_mod._flush_frame()

  # Blocking read: render a frame, then park up to `wait_ms` for a key.
  def _blocking_read(n, wait_ms):
    step = wait_ms if (wait_ms and wait_ms > 0) else 16
    while True:
      if vs_mod._stop_requested():
        raise vs_mod.StopApp()
      _do_frame()
      s = vs_mod._read_available(n)
      if s:
        return s
      vs_mod._wait_input(step)

  vs_mod._blocking_read = _blocking_read

  # time.sleep keeps callbacks animating during the wait.
  def _patched_sleep(s):
    if vs_mod._in_callback:
      _builtin_sleep(max(0, s))
      return
    end = _t.time() + s
    has_cb = vs_mod._registered_callback is not None
    while True:
      if vs_mod._stop_requested():
        raise vs_mod.StopApp()
      remaining = end - _t.time()
      if remaining <= 0:
        break
      _do_frame()
      chunk = 0.016 if has_cb else remaining
      vs_mod._wait_input(min(remaining, chunk) * 1000)

  _t.sleep = _patched_sleep

  # Some apps drive their render loop with time.sleep_ms()/sleep_us() rather than
  # time.sleep() or pdeck.delay_tick() (e.g. graph's main loop). On the device the
  # display task renders callbacks independently of how the app loop waits, but
  # here a frame is only produced from inside the patched sleep. Route the ms/us
  # helpers through it too, otherwise such apps spin without ever rendering and
  # appear frozen. (The 75 fps gate in _do_frame still caps redraw volume.)
  _t.sleep_ms = lambda ms: _patched_sleep(ms / 1000)
  _t.sleep_us = lambda us: _patched_sleep(us / 1_000_000)

  # ── load + run ──
  with open(code_path) as f:
    code_str = f.read()

  namespace = {'__name__': '__emulator__'}
  try:
    exec(compile(code_str, code_path, 'exec'), namespace)
  except SyntaxError as e:
    _post({'type': 'error', 'message': f'Syntax error: {e}'})
    return

  app_main = namespace.get('main')
  if not callable(app_main):
    _post({'type': 'error', 'message': 'No main() function found in app'})
    return

  vs = vs_mod.VscreenStream()

  try:
    app_main(vs, args_list if args_list else ['app'])
  except vs_mod.StopApp:
    pass
  except Exception:
    import traceback
    _post({'type': 'error', 'message': traceback.format_exc()})

  _post({'type': 'done'})
  _post({'type': 'mode', 'graphics': False})
