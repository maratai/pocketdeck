import time as _time

_last_t = 0
_fps = 0
_frame_count = 0

def show_fps(v):
  global _last_t, _fps, _frame_count
  now = _time.ticks_ms()
  _frame_count += 1
  if _time.ticks_diff(now, _last_t) >= 1000:
    _fps = _frame_count
    _frame_count = 0
    _last_t = now
  v.set_font("u8g2_font_profont11_mf")
  v.set_draw_color(1)
  v.draw_str(350, 2, f"{_fps}fps")
