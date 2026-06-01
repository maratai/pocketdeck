import time as _time
import sys

def vscreen(screen_num=None):
  from vscreen import VscreenStream
  return VscreenStream()

def get_screen_size():
  return (400, 240)

def get_screen_num():
  return 2

def change_screen(screen):
  pass

def show_screen_num():
  pass

_inverted = False

def screen_invert(value=None):
  global _inverted
  if value is None:
    return _inverted
  _inverted = bool(value)
  import json
  from js import emulator_post_raw
  emulator_post_raw(json.dumps({'type': 'invert', 'value': _inverted}))
  return _inverted

def wifi_connected():
  return False

def led(led_index, brightness=0):
  pass

def rtc(t=None):
  import time
  lt = _time.localtime()
  return (lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_wday, lt.tm_hour, lt.tm_min, lt.tm_sec)

def shutdown():
  pass

def delay_tick(tick):
  _time.sleep(tick / 1000)

def change_priority(p=False):
  pass

def clipboard_copy(s):
  if isinstance(s, (bytes, bytearray)):
    s = s.decode('utf-8', 'replace')
  from js import emulator_clip_set
  emulator_clip_set(str(s))

def clipboard_paste():
  # Device returns bytes (mp_obj_new_bytes); match that so callers like PEM's
  # insert_str (which does bytearray.extend) get bytes, not str.
  from js import emulator_clip_get
  return str(emulator_clip_get()).encode('utf-8')

def cmd_exists(screen_num):
  return False

def cmd_execute(command, screen_cmdshell, screen_dest=None):
  pass

def set_default_terminal_font_size(size):
  pass

def get_default_terminal_font_size():
  return 1

def update_app_list(screen_num, value):
  pass

def init():
  pass

def shared_filelist(filename=None):
  return []

def completion():
  return ('', 0)

def run_completion(timeout_ms=None):
  return None

def callback_completion(fn=None):
  pass
