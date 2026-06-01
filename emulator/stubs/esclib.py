#
# Escape sequence lib
# Copyright Nunomo LLC.
# MIT license
#

class esclib:
  def erase_screen(self):
    return "\x1b[2J"
  def home(self):
    return "\x1b[H"
  def erase_to_end_of_current_line(self):
    return "\x1b[K"
  def cur_up(self, num=1):
    return f"\x1b[{num}A" if num != 1 else "\x1b[A"
  def cur_down(self, num=1):
    return f"\x1b[{num}B" if num != 1 else "\x1b[B"
  def cur_left(self, num=1):
    return f"\x1b[{num}D" if num != 1 else "\x1b[D"
  def cur_right(self, num=1):
    return f"\x1b[{num}C" if num != 1 else "\x1b[C"
  def raw_mode(self, mode):
    return "\x1b[?1h" if mode else "\x1b[?1l"
  def cursor_mode(self, mode):
    return "\x1b[?25h" if mode else "\x1b[?25l"
  def wraparound_mode(self, mode):
    return "\x1b[?7h" if mode else "\x1b[?7l"
  def display_mode(self, mode):
    return "\x1b[?5000h" if mode else "\x1b[?5000l"
  def move_cursor(self, x, y):
    return f"\x1b[{x};{y}H"
  def set_font_color(self, color):
    return f"\x1b[{color}m"
  def reset_font_color(self):
    return "\x1b[39;22;23m"
  def bold(self):
    return "\x1b[1m"
  def bold_off(self):
    return "\x1b[22m"
