import math
import time as _time

# === Easing functions (t: 0.0 -> 1.0) ===

def linear(t):
  return t

def ease_in(t):
  return t * t

def ease_out(t):
  return 1 - (1 - t) * (1 - t)

def ease_in_out(t, m=0.5):
  if t < m:
    return ease_in(t / m) * m
  else:
    return m + ease_out((t - m) / (1 - m)) * (1 - m)

def ease_out_in(t, m=0.5):
  if t < m:
    return ease_out(t / m) * m
  else:
    return m + ease_in((t - m) / (1 - m)) * (1 - m)

def spring(t, b=3, d=5):
  if t <= 0:
    return 0.0
  if t >= 1:
    return 1.0
  return 1 - math.exp(-d * t) * math.cos(b * math.pi * t)

def jump(t):
  return 1.0 if t >= 1.0 else 0.0


def _interpolate(keyframes, t):
  """Interpolate across multiple keyframes. keyframes=[fn, v0, v1, ...] or [fn, v0, v1]."""
  fn = keyframes[0]
  values = keyframes[1:]
  if len(values) == 1:
    return values[0]
  n = len(values) - 1
  segment = min(int(t * n), n - 1)
  local_t = t * n - segment
  v0 = values[segment]
  v1 = values[segment + 1]
  norm = fn(local_t)
  return v0 + (v1 - v0) * norm


class anm_object:
  def __init__(self, duration_ms, props, loop=False, auto_unregister=False):
    self._duration_ms = duration_ms
    self._props = props
    self._loop = loop
    self._auto_unregister = auto_unregister
    self._start_ms = _time.ticks_ms()
    self._current_t = 0.0
    self._done = False
    # Initialize prop values
    for key, keyframes in props.items():
      object.__setattr__(self, key, keyframes[1])

  def _update(self, t_ms):
    elapsed = _time.ticks_diff(t_ms, self._start_ms)
    if self._duration_ms <= 0:
      self._current_t = 1.0
    else:
      self._current_t = elapsed / self._duration_ms
    if self._loop:
      self._current_t = self._current_t % 1.0
    else:
      self._current_t = max(0.0, min(1.0, self._current_t))
      if elapsed >= self._duration_ms:
        self._done = True
    for key, keyframes in self._props.items():
      val = _interpolate(keyframes, self._current_t)
      object.__setattr__(self, key, val)

  def seek(self, norm_t):
    self._current_t = max(0.0, min(1.0, norm_t))
    for key, keyframes in self._props.items():
      object.__setattr__(self, key, _interpolate(keyframes, self._current_t))

  def get_time(self):
    return self._current_t % 1.0 if self._loop else self._current_t

  def get_elapsed(self):
    return _time.ticks_diff(_time.ticks_ms(), self._start_ms) / self._duration_ms


class anm_sequencer:
  def __init__(self):
    self._objects = {}

  def register(self, key, obj, seek_to=None):
    if seek_to is not None and seek_to > 0 and obj._duration_ms > 0:
      elapsed = int(seek_to * obj._duration_ms)
      obj._start_ms = _time.ticks_ms() - elapsed
    else:
      obj._start_ms = _time.ticks_ms()
    self._objects[key] = obj

  def unregister(self, key):
    self._objects.pop(key, None)

  def update(self, t_ms):
    to_remove = []
    for key, obj in self._objects.items():
      obj._update(t_ms)
      if obj._done and obj._auto_unregister:
        to_remove.append(key)
    for k in to_remove:
      del self._objects[k]

  def get_obj(self, key):
    return self._objects.get(key)

  def __iter__(self):
    return iter(self._objects.values())
