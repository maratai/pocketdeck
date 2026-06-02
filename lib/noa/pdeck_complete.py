# TAB completion handler invoked from cmdshell.c via pdeck.callback_completion.
#
# Flow per invocation:
#   1. Read current command line and cursor via pdeck.completion()
#   2. Pick a completion source (apps / flags / files / history)
#   3. If one match: splice it in. If many: show a menu, let user pick.
#   4. Always call pdeck.completion(out, cursor) — even on error — so the
#      cmdshell task waiting on the finish_queue unblocks.

import os
import pdeck
import pdeck_utils
import sys

_DB = None
_DB_PATH = '/sd/lib/data/apps_db.json'
_HISTORY_FMT = '/cmd_history/cmd{:02d}'
_MAX_ITEMS = 8
_MAX_ITEM_WIDTH = 60

ESC = '\x1b'
SAVE = ESC + '7'
RESTORE = ESC + '8'
ERASE_DOWN = ESC + '[J'
ERASE_LINE = ESC + '[K'
BOLD= "\x1b[1m"
BOLD_OFF = "\x1b[22m"


def _load_db():
  global _DB
  if _DB is not None:
    return _DB
  try:
    import json
    with open(_DB_PATH) as f:
      _DB = json.load(f).get('apps', {})
  except Exception:
    _DB = {}
  return _DB


def _tokenize(cmd):
  toks = []
  i, n = 0, len(cmd)
  while i < n:
    while i < n and cmd[i] == ' ':
      i += 1
    if i >= n:
      break
    s = i
    while i < n and cmd[i] != ' ':
      i += 1
    toks.append((cmd[s:i], s, i))
  return toks


def _current_token(cmd, cursor):
  toks = _tokenize(cmd)
  for idx, (t, s, e) in enumerate(toks):
    if s <= cursor <= e:
      return idx, cmd[s:cursor], s, e, toks
  idx = sum(1 for (_, s, _) in toks if s < cursor)
  return idx, '', cursor, cursor, toks


def _is_dir(path):
  try:
    return os.stat(path)[0] & 0x4000 != 0
  except OSError:
    return False


# Each source returns a list of (value, label) tuples. `value` is what gets
# spliced into the command; `label` is what shows in the menu.

def _candidates_apps(prefix):
  db = _load_db()
  out = []
  for n in sorted(db):
    if not n.startswith(prefix):
      continue
    summary = db[n].get('summary', '')
    label = n + '  ' + summary if summary else n
    out.append((n, label))
  return out


def _candidates_flags(cmd_name, prefix):
  info = _load_db().get(cmd_name)
  if not info:
    return []
  return [(f, f) for f in sorted(info.get('flags', []))
          if f.startswith(prefix)]


def _candidates_files(prefix):
  if '/' in prefix:
    slash = prefix.rfind('/')
    dir_part = prefix[:slash + 1]
    name_part = prefix[slash + 1:]
    base = dir_part if dir_part != '/' else '/'
    base_clean = base.rstrip('/') if base != '/' else '/'
  else:
    dir_part = ''
    name_part = prefix
    base = '.'
    base_clean = base.rstrip('/') if base != '/' else '/'
  try:
    print(base_clean)
    entries = os.listdir(base_clean)
  except OSError:
    return []
  out = []
  #base_clean = base.rstrip('/') if base != '/' else '/'
  for e in entries:
    if not e.startswith(name_part):
      continue
    full = dir_part + e
    if _is_dir(base_clean + ('' if base_clean == '/' else '/') + e):
      full += '/'
    out.append((full, full))
  out.sort()
  return out


def _load_history(screen_num):
  try:
    with open(_HISTORY_FMT.format(screen_num)) as f:
      return [l.rstrip('\n') for l in f if l.strip()]
  except OSError:
    return []


def _candidates_history(cmd, screen_num):
  toks = _tokenize(cmd)
  if not toks:
    return []
  first = toks[0][0]
  seen = set()
  matches = []
  for h in _load_history(screen_num):
    if h == cmd or h in seen:
      continue
    h_toks = h.split()
    if not h_toks or h_toks[0] != first:
      continue
    seen.add(h)
    matches.append((h, h))
  return matches


def _looks_like_path(prefix):
  return ('/' in prefix) or prefix.startswith('.') or prefix.startswith('~')


def _pick_source(cmd, cursor, screen_num):
  """Return ('mode', items, replace_start, replace_end) for the cursor.

  mode == 'arg'   : items will replace cmd[replace_start:replace_end]
  mode == 'whole' : items will replace the whole cmd
  """
  idx, prefix, rs, re_, toks = _current_token(cmd, cursor)
  if idx == 0:
    return 'arg', _candidates_apps(prefix), rs, re_
  first = toks[0][0]
  db = _load_db()
  info = db.get(first, {})
  if prefix.startswith('-'):
    return 'arg', _candidates_flags(first, prefix), rs, re_
  if _looks_like_path(prefix) or info.get('takes_file'):
    files = _candidates_files(prefix)
    if files:
      return 'arg', files, rs, re_
  return 'whole', _candidates_history(cmd, screen_num), 0, len(cmd)


def _show_menu(vs_out, vs_in, items):
  """Interactive picker. Returns selected index or None on cancel."""

  if not items:
    return None
  if len(items) == 1:
    return 0
  selected = 0

  # Clamp to the actual terminal so the menu fits and the row count we feed
  # into the pre-scroll matches what we'll draw.
  try:
    term_w, term_h = vs_in.get_terminal_size()
  except Exception:
    term_w, term_h = 50, 15
  max_w = max(20, term_w - 2)
  max_h = max(2, term_h - 2)
  visible = min(_MAX_ITEMS, len(items), max_h)
  top = 0

  # Reserve `visible` empty rows below the input cursor. If we're near the
  # bottom of the screen this scrolls the input row up; either way, after
  # this any drawing we do cannot scroll, so the DECSC-saved position stays
  # anchored to the input line. Without this, drawing the menu near the
  # bottom would scroll mid-render and the '>' marker would disappear.
  # Use IND (ESC D) — line feed without CR — so the cursor column is kept.
  # Plain '\n' resets x to 0 on this terminal (see displayapi.c LF handling),
  # which would corrupt the saved cursor.
  vs_out.write('\x1bD' * visible)
  vs_out.write('\x1b[' + str(visible) + 'A')
  vs_out.write(SAVE)

  def render():
    vs_out.write(RESTORE)
    vs_out.write(ERASE_DOWN)
    for i in range(visible):
      idx = top + i
      on_cursor = True if idx == selected+top else False
      if on_cursor:
        marker = '❯  '
      else:
        marker = '  '
      line = marker + (BOLD if on_cursor else '') + items[idx][1] 
      if len(line) > max_w:
        line = line[:max_w - 3] + '...'
      line += (BOLD_OFF if on_cursor else '')
      vs_out.write('\r\n' + ERASE_LINE + line)
    vs_out.write(RESTORE)

  render()

  result = None
  buf = ''
  done = False
  esc_idle = 0
  while not done:
    ret = vs_in.read_nb(8)
    if not ret:
      pdeck.delay_tick(100)
      continue
    if ret:
      nread, data = ret
    if nread == 0:
      pdeck.delay_tick(1)
      if buf == ESC:
        esc_idle += 1
        if esc_idle > 5:
          # Lone ESC with no follow-up → cancel.
          result = None
          done = True
      continue
    esc_idle = 0
    buf += data
    while buf and not done:
      consumed, key = _consume_key(buf)
      #print(key)
      if consumed == 0:
        break  # incomplete escape, wait for more input
      buf = buf[consumed:]
      if key == 'enter':
        result = top + selected
        done = True
      elif key == 'cancel':
        result = None
        done = True
      elif key == 'up':
        if selected > 0:
          selected -= 1
        elif top > 0:
          top -= 1
        render()
      elif key == 'down':
        if top + selected < len(items) - 1:
          if selected < visible - 1:
            selected += 1
          else:
            top += 1
          render()

  vs_out.write(RESTORE + ERASE_DOWN)
  return result


def _consume_key(buf):
  """Consume one key from buf. Return (chars_consumed, name_or_char)."""
  c = buf[0]
  if c == '\r' or c == '\n':
    return 1, 'enter'
  if c == '\x07' or c == '\x08' or c == '\x1b':
    if c == '\x1b' and len(buf) >= 3 and (buf[1] == '[' or buf[1] == 'O'):
      a = buf[2]
      if a == 'A':
        return 3, 'up'
      if a == 'B':
        return 3, 'down'
      if a == 'C':
        return 3, 'right'
      if a == 'D':
        return 3, 'left'
      return 3, 'other'
    if c == '\x1b' and len(buf) < 3:
      return 0, None  # wait for more
    return 1, 'cancel'
  if c == '\t':
    return 1, 'down'  # TAB again cycles selection forward
  return 1, c


def _splice_arg(cmd, value, rs, re_):
  new_cmd = cmd[:rs] + value + cmd[re_:]
  new_cursor = rs + len(value)
  # If we completed a file (no trailing /) or an app/flag, append a space when
  # there's no following character — feels natural and matches fish.
  if not value.endswith('/') and (new_cursor >= len(new_cmd)
                                  or new_cmd[new_cursor] != ' '):
    new_cmd = new_cmd[:new_cursor] + ' ' + new_cmd[new_cursor:]
    new_cursor += 1
  return new_cmd, new_cursor


def handle(_arg=None):
  out_cmd, out_cursor = '', 0
  screen_num = pdeck.get_screen_num()
  vs = pdeck_utils.vscreen_stream(screen_num)
  try:
    cmd, cursor = pdeck.completion()
    out_cmd, out_cursor = cmd, cursor
    mode, items, rs, re_ = _pick_source(cmd, cursor, screen_num)
    if not items:
      return
    vs.write("\x1b[?1h") #raw_mode on
    chosen = _show_menu(vs, vs.v, items)
    if chosen is None:
      return
    value = items[chosen][0]
    if mode == 'whole':
      out_cmd, out_cursor = value, len(value)
    else:
      out_cmd, out_cursor = _splice_arg(cmd, value, rs, re_)
  except Exception as e:
    print('completion error:', e)
    sys.print_exception(e)
  finally:
    vs.write("\x1b[?1l") #raw_mode off
    pdeck.completion(out_cmd, out_cursor)
