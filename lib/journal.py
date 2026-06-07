import os
import sys
import re
import datetime
import time
import math
import mouse
import esclib as elib
import pdeck
import pdeck_utils
import ls

import anm

DAY_SEC = 60 * 60 * 24


def file_exists(name):
  if name is None:
    return False
  try:
    os.stat(name)
    return True
  except OSError:
    return False


def dir_exists(name):
  if name is None:
    return False
  try:
    st = os.stat(name)
    return (st[0] & 0x4000) != 0
  except OSError:
    return False


def join_path(base, name):
  if base == '/':
    return '/' + name
  if base == '' or base == '.':
    return name
  return base + '/' + name


def normalize_inputs(inputs):
  if inputs is None:
    return []
  if isinstance(inputs, str):
    return [inputs]
  return inputs


def expand_input_files(inputs):
  out = []
  seen = {}

  for q in normalize_inputs(inputs):
    if dir_exists(q):
      ret = ls.list_file(q)
      if not ret:
        continue
      dirname, filelist = ret
      for item in filelist:
        full = join_path(dirname, item)
        if dir_exists(full):
          continue
        if item.lower().endswith('.md') and full not in seen:
          out.append(full)
          seen[full] = True
      continue

    if file_exists(q):
      if q not in seen:
        out.append(q)
        seen[q] = True
      continue

    ret = ls.list_file(q)
    if not ret:
      continue
    dirname, filelist = ret
    for item in filelist:
      full = join_path(dirname, item)
      if dir_exists(full):
        continue
      if full not in seen:
        out.append(full)
        seen[full] = True

  return out


def clamp01(v):
  if v < 0:
    return 0.0
  if v > 1:
    return 1.0
  return v


def is_leap_year(year):
  if (year % 400) == 0:
    return True
  if (year % 100) == 0:
    return False
  return (year % 4) == 0


def days_in_month(year, month):
  if month == 2:
    if is_leap_year(year):
      return 29
    return 28
  if month == 4 or month == 6 or month == 9 or month == 11:
    return 30
  return 31


def parse_iso_date(s):
  try:
    parts = s.split('-')
    if len(parts) != 3:
      return None
    return (int(parts[0]), int(parts[1]), int(parts[2]))
  except Exception:
    return None


def parse_default_date_from_filename(path):
  if path is None:
    return None
  name = path
  idx = name.rfind('/')
  if idx >= 0:
    name = name[idx + 1:]
  if name.lower().endswith('.md'):
    name = name[:-3]
  return parse_iso_date(name)


def format_ymd_iso(d):
  return '%04d-%02d-%02d' % (d[0], d[1], d[2])


def first_of_month(d):
  return (d[0], d[1], 1)


def add_days_ymd(d, delta):
  year = d[0]
  month = d[1]
  day = d[2]

  while delta > 0:
    dim = days_in_month(year, month)
    if day < dim:
      day += 1
    else:
      day = 1
      month += 1
      if month > 12:
        month = 1
        year += 1
    delta -= 1

  while delta < 0:
    if day > 1:
      day -= 1
    else:
      month -= 1
      if month < 1:
        month = 12
        year -= 1
      day = days_in_month(year, month)
    delta += 1

  return (year, month, day)


def iso_date_key(d):
  return '%d-%d-%d' % (d[0], d[1], d[2])


def iso_month_key(d):
  return '%04d-%02d' % (d[0], d[1])


class JournalCache:
  def __init__(self, inputs):
    self.month_list = (
      '', 'January', 'Febrary', 'March', 'April',
      'May', 'June', 'July', 'August', 'September',
      'October', 'November', 'December'
    )
    self.re_date = re.compile('^(\\#+)\\s+<(.+)>')
    self.re_item = re.compile('^-\\s*\[(.+)\]\\s+(.+)')
    self.filenames = expand_input_files(inputs)
    self.reset()

  def reset(self):
    self.months = {}
    self.render_base = {}
    self.latest_date = None
    self.total_bytes = 0
    self.loaded_bytes = 0
    self.state_index = 0
    self.pending_months = {}
    self.loading = False
    self.done = False
    self._states = []

    for filename in self.filenames:
      try:
        st = os.stat(filename)
        size = st[6]
      except Exception:
        size = 0
      self.total_bytes += size
      self._states.append({
        'filename': filename,
        'size': size,
        'fh': None,
        'done': False,
        'curdate': None,
        'first_date': None,
        'default_date': parse_default_date_from_filename(filename),
        'reversed_order': 1,
        'reversed_known': False,
        'pending_entries': []
      })

    self.loading = len(self._states) > 0
    self.done = len(self._states) == 0

  def progress(self):
    if self.done:
      return 1.0
    if self.total_bytes <= 0:
      return 0.0
    if self.loaded_bytes >= self.total_bytes:
      return 1.0
    return self.loaded_bytes / self.total_bytes

  def _parse_value(self, result):
    try:
      fields = result.split(':')
      if len(fields) == 2 and fields[0].isdigit() and fields[1].isdigit():
        hours = float(fields[0]) + float(fields[1]) / 60.0
        return ('time', hours)
    except Exception:
      pass

    try:
      return float(result)
    except ValueError:
      return None

  def _ensure_month(self, d):
    key = iso_month_key(d)
    if key not in self.months:
      self.months[key] = {
        'year': d[0],
        'month': d[1],
        'task_list': {},
        'n_task_list': {},
        'dirty': True
      }
    return self.months[key]

  def _invalidate_month(self, month_key):
    if month_key in self.render_base:
      del self.render_base[month_key]
    if month_key in self.months:
      self.months[month_key]['dirty'] = True
    self.pending_months[month_key] = True

  def _store_numeric(self, task_name, d, fval):
    month = self._ensure_month(d)
    if task_name not in month['n_task_list']:
      month['n_task_list'][task_name] = {}
    if task_name == 'Weight' and (not isinstance(fval, tuple)) and fval < 100:
      fval *= 2.204
    month['n_task_list'][task_name][iso_date_key(d)] = fval
    self._invalidate_month(iso_month_key(d))

  def _store_text(self, task_name, d, result):
    month = self._ensure_month(d)
    if task_name not in month['task_list']:
      month['task_list'][task_name] = {}
    month['task_list'][task_name][iso_date_key(d)] = result
    self._invalidate_month(iso_month_key(d))

  def _flush_state_block(self, state):
    curdate = state['curdate']
    if curdate is None:
      return
    for task_name, result_blob in state['pending_entries']:
      result_list = result_blob.split(',')
      for i, result in enumerate(result_list):
        result = result.strip()
        if result == '':
          continue
        offset = i if state['reversed_order'] == 1 else -i
        d = add_days_ymd(curdate, -offset)
        fval = self._parse_value(result)
        if fval is None:
          self._store_text(task_name, d, result)
        else:
          self._store_numeric(task_name, d, fval)
    state['pending_entries'] = []

  def _close_state(self, state):
    try:
      if state['fh']:
        state['fh'].close()
    except Exception:
      pass
    state['fh'] = None
    state['done'] = True

  def _finish_state(self, state):
    if not state['reversed_known']:
      state['reversed_known'] = True
      state['reversed_order'] = 1
    self._flush_state_block(state)
    self._close_state(state)

  def _consume_line(self, state, line):
    if line.startswith('#'):
      head = self.re_date.search(line)
      if head:
        date_string = head.group(2)
        newdate = parse_iso_date(date_string[0:10])
        if newdate is None:
          return
        if self.latest_date is None or newdate > self.latest_date:
          self.latest_date = newdate
        if state['curdate'] is None:
          state['curdate'] = newdate
          state['first_date'] = newdate
          state['pending_entries'] = []
          return
        if not state['reversed_known']:
          if state['first_date'] is not None and state['first_date'] < newdate:
            state['reversed_order'] = -1
          else:
            state['reversed_order'] = 1
          state['reversed_known'] = True
        self._flush_state_block(state)
        state['curdate'] = newdate
        state['pending_entries'] = []
      return

    if not line.startswith('-'):
      return

    match = self.re_item.search(line)
    if not match:
      return

    if state['curdate'] is None:
      default_date = state.get('default_date')
      if default_date is None:
        return
      state['curdate'] = default_date
      if state['first_date'] is None:
        state['first_date'] = default_date
      if self.latest_date is None or default_date > self.latest_date:
        self.latest_date = default_date

    state['pending_entries'].append((match.group(2), match.group(1)))

  def step(self, max_lines = 120, max_ms = 18):
    changed = self.pending_months
    self.pending_months = {}

    if self.done:
      return list(changed)

    t0 = time.ticks_ms()
    line_count = 0
    states_len = len(self._states)
    if states_len == 0:
      self.done = True
      self.loading = False
      return list(changed)

    while line_count < max_lines:
      state = self._states[self.state_index]
      self.state_index += 1
      if self.state_index >= states_len:
        self.state_index = 0

      if state['done']:
        if self._all_done():
          self.done = True
          self.loading = False
          break
        if time.ticks_diff(time.ticks_ms(), t0) >= max_ms:
          break
        continue

      if state['fh'] is None:
        try:
          state['fh'] = open(state['filename'], 'r')
        except Exception:
          self._close_state(state)
          continue

      line = state['fh'].readline()
      if line == '':
        self._finish_state(state)
        if self._all_done():
          self.done = True
          self.loading = False
          break
        if time.ticks_diff(time.ticks_ms(), t0) >= max_ms:
          break
        continue

      self.loaded_bytes += len(line)
      self._consume_line(state, line)
      line_count += 1

      if time.ticks_diff(time.ticks_ms(), t0) >= max_ms:
        break

    if self._all_done():
      self.done = True
      self.loading = False

    for month_key in self.pending_months:
      changed[month_key] = True
    self.pending_months = {}
    return list(changed)

  def _all_done(self):
    for state in self._states:
      if not state['done']:
        return False
    return True

  def _build_month_days(self, month_date):
    out = []
    year = month_date[0]
    month = month_date[1]
    for day in range(1, days_in_month(year, month) + 1):
      d = (year, month, day)
      out.append((iso_date_key(d), day))
    return out

  def _entry_value(self, entry):
    if isinstance(entry, tuple) and entry[0] == 'time':
      return entry[1]
    return entry

  def _entry_format(self, entry):
    if isinstance(entry, tuple) and entry[0] == 'time':
      val = entry[1]
      minutes = int(val * 60)
      return '%d:%02d' % (minutes // 60, minutes % 60)
    return '%.1f' % entry

  def _build_render_base(self, month_date):
    month_key = iso_month_key(month_date)
    month_data = self.months.get(month_key)
    month_days = self._build_month_days(month_date)
    month_title = self.month_list[month_date[1]][:3]

    task_rows = []
    if month_data:
      for task in sorted(month_data['task_list']):
        tdata = month_data['task_list'][task]
        boxes = []
        for dt, day in month_days:
          checked = False
          if dt in tdata:
            val = tdata[dt]
            if val == 'X' or val == 'x':
              checked = True
          boxes.append((70 + day * 10, checked))
        task_rows.append((task[:10], boxes))

    graph_task_keys = []
    graph_tabs = []
    graph_cache = {}
    if month_data:
      graph_task_keys = sorted(month_data['n_task_list'])
      for i, key in enumerate(graph_task_keys):
        graph_tabs.append((20 + i * 90, 10 + i * 90, key[:10], key))

      size = 60
      for task in graph_task_keys:
        tdata = month_data['n_task_list'][task]
        raw_points = []
        min_entry = None
        max_entry = None
        min_val = None
        max_val = None

        for dt, day in month_days:
          if dt not in tdata:
            continue
          entry = tdata[dt]
          val = self._entry_value(entry)
          raw_points.append((day, entry, val))
          if min_val is None or val < min_val:
            min_val = val
            min_entry = entry
          if max_val is None or val > max_val:
            max_val = val
            max_entry = entry

        if min_val is None:
          continue

        points = []
        for day, entry, val in raw_points:
          if max_val == min_val:
            y = int(size / 2)
          else:
            y = size - int((val - min_val) * (size / (max_val - min_val)))
          points.append((70 + day * 10 + 4, 20 + y))

        graph_cache[task] = {
          'min_label': self._entry_format(min_entry),
          'max_label': self._entry_format(max_entry),
          'points': points
        }

    base = {
      'month_key': month_key,
      'month_title': month_title,
      'month_days': month_days,
      'task_rows': task_rows,
      'graph_task_keys': graph_task_keys,
      'graph_tabs': graph_tabs,
      'graph_cache': graph_cache,
      'has_data': bool(task_rows or graph_cache)
    }
    self.render_base[month_key] = base
    if month_data:
      month_data['dirty'] = False
    return base

  def get_render(self, month_date, cur_n_task = None):
    month_key = iso_month_key(month_date)
    month_data = self.months.get(month_key)
    base = self.render_base.get(month_key)
    if base is None or (month_data and month_data['dirty']):
      base = self._build_render_base(month_date)

    graph_task_keys = base['graph_task_keys']
    if len(graph_task_keys) == 0:
      cur_n_task = None
    elif cur_n_task not in graph_task_keys:
      cur_n_task = graph_task_keys[0]

    render = {
      'month_key': base['month_key'],
      'month_title': base['month_title'],
      'month_days': base['month_days'],
      'task_rows': base['task_rows'],
      'graph_task_keys': base['graph_task_keys'],
      'graph_tabs': base['graph_tabs'],
      'graph_cache': base['graph_cache'],
      'cur_n_task': cur_n_task,
      'has_data': base['has_data']
    }
    return render


class graph_diary:
  def __init__(self, vs):
    self.vs = vs
    self.v = vs.v
    self.mouse = mouse.mouse(self.v)
    self.seq = anm.anm_sequencer()
    obj = anm.anm_object(350,
    { 'dither' : [ anm.ease_out,0, 16.1 ]})
    self.seq.register('chart_dither', obj)
    self.screen_size = pdeck.get_screen_size()
    self.width = self.screen_size[0]
    self.height = self.screen_size[1]

    self.goffset = [0, 10]
    self.groffset = [0, 140]
    self.org_filename = None
    self.cache = None
    self.auto_follow_latest = True
    self.user_navigated = False
    self.cur_n_task_by_month = {}
    self.achievement_scroll_by_month = {}
    self.achievement_scroll_anim = 0.0
    self.achievement_scroll_anim_month = None
    self.last_achievement_slider = 255

    self.last_mouse_active = False
    self.last_mouse_col = None
    self.last_progress_bucket = -1
    self.key_event = False
    self.dirty = True

    self.slide_dir = 0
    self.prev_render = None
    self.current_render = None
    self.panel_anim = None
    self.graph_anim = None

    self.shifted_day = None
    self.update_time()
    self.shifted_day = (self.year, self.month, 1)
    self._start_panel_anim(0, 0, 1, 1, 120)
    self.current_render = self._empty_render()

  def _empty_render(self):
    return {
      'month_key': iso_month_key(self.shifted_day),
      'month_title': '',
      'month_days': [],
      'task_rows': [],
      'graph_task_keys': [],
      'graph_tabs': [],
      'graph_cache': {},
      'cur_n_task': None,
      'has_data': False
    }

  def update_time(self):
    ctime = time.gmtime(time.time() + 60 * 15 * pdeck_utils.timezone)
    self.hour = ctime[3]
    self.year = ctime[0]
    self.month = ctime[1]
    self.day = ctime[2]
    self.week = ctime[6]
    self.minute = ctime[4]
    self.second = ctime[5]

  def _mark_dirty(self):
    self.dirty = True

  def _visible_achievement_rows(self):
    top = self.goffset[1] + 40
    bottom = self.groffset[1]
    rows = (bottom - top) // 16
    if rows < 1:
      return 1
    return rows

  def _clamp_achievement_scroll(self, month_key, total_rows):
    limit = total_rows - self._visible_achievement_rows()
    if limit < 0:
      limit = 0
    cur = self.achievement_scroll_by_month.get(month_key, 0)
    if cur < 0:
      cur = 0
    if cur > limit:
      cur = limit
    self.achievement_scroll_by_month[month_key] = cur
    return cur

  def _sync_achievement_scroll(self, month_key, total_rows, snap = False):
    target = self._clamp_achievement_scroll(month_key, total_rows)
    if snap or self.achievement_scroll_anim_month != month_key:
      self.achievement_scroll_anim_month = month_key
      self.achievement_scroll_anim = float(target)
    return target

  def _current_achievement_scroll(self, month_key, total_rows):
    target = self._clamp_achievement_scroll(month_key, total_rows)
    if self.achievement_scroll_anim_month != month_key:
      return float(target)
    pos = self.achievement_scroll_anim
    if pos < 0:
      pos = 0.0
    limit = total_rows - self._visible_achievement_rows()
    if limit < 0:
      limit = 0
    if pos > limit:
      pos = float(limit)
    return pos

  def _update_achievement_scroll_anim(self):
    if self.current_render is None:
      return False
    month_key = self.current_render['month_key']
    total_rows = len(self.current_render['task_rows'])
    target = self._sync_achievement_scroll(month_key, total_rows)
    if self.achievement_scroll_anim_month != month_key:
      self.achievement_scroll_anim_month = month_key
      self.achievement_scroll_anim = float(target)
      return True
    diff = float(target) - self.achievement_scroll_anim
    if diff > -0.001 and diff < 0.001:
      if self.achievement_scroll_anim != float(target):
        self.achievement_scroll_anim = float(target)
        return True
      return False
    self.achievement_scroll_anim += diff * 0.35
    if diff > 0 and self.achievement_scroll_anim > target:
      self.achievement_scroll_anim = float(target)
    if diff < 0 and self.achievement_scroll_anim < target:
      self.achievement_scroll_anim = float(target)
    self._mark_dirty()
    return True

  def _achievement_scroll_animating(self):
    if self.current_render is None:
      return False
    month_key = self.current_render['month_key']
    total_rows = len(self.current_render['task_rows'])
    target = self._clamp_achievement_scroll(month_key, total_rows)
    if self.achievement_scroll_anim_month != month_key:
      return False
    diff = self.achievement_scroll_anim - float(target)
    if diff < 0:
      diff = -diff
    return diff >= 0.001

  def _scroll_achievements(self, delta):
    if self.current_render is None:
      return False
    month_key = self.current_render['month_key']
    total_rows = len(self.current_render['task_rows'])
    cur = self._clamp_achievement_scroll(month_key, total_rows)
    limit = total_rows - self._visible_achievement_rows()
    if limit < 0:
      limit = 0
    nxt = cur + delta
    if nxt < 0:
      nxt = 0
    if nxt > limit:
      nxt = limit
    if nxt == cur:
      return False
    self.achievement_scroll_by_month[month_key] = nxt
    if self.achievement_scroll_anim_month != month_key:
      self.achievement_scroll_anim_month = month_key
      self.achievement_scroll_anim = float(cur)
    self._mark_dirty()
    return True

  def handle_achievement_slider(self, raw):
    if raw == 255:
      self.last_achievement_slider = 255
      return False
    if raw < 0:
      raw = 0
    if raw > 100:
      raw = 100
    if self.last_achievement_slider == 255:
      self.last_achievement_slider = raw
      return False
    step = 5
    delta = 0
    diff = raw - self.last_achievement_slider
    while diff >= step:
      delta += 1
      self.last_achievement_slider += step
      diff = raw - self.last_achievement_slider
    while diff <= -step:
      delta -= 1
      self.last_achievement_slider -= step
      diff = raw - self.last_achievement_slider
    if delta:
      return self._scroll_achievements(-delta)
    return False

  def _start_panel_anim(self, slide_start, slide_end, reveal_start, reveal_end, duration):
    self.panel_anim = anm.anm_object(duration, {
      'slide': [anm.ease_out, slide_start, slide_end],
      'reveal': [anm.ease_out, reveal_start, reveal_end]
    })
    self.panel_anim.goal = 1
    self.seq.register('panel', self.panel_anim)
    self._mark_dirty()

  def _panel_animating(self):
    obj = self.seq.get_obj('panel')
    return not obj.get_time == 1.0
    

  def _graph_signature(self, render):
    if render is None:
      return None

    task = render['cur_n_task']
    if task is None:
      return (render['month_key'], None, 0, None, None)

    cache = render['graph_cache'].get(task)
    if cache is None:
      return (render['month_key'], task, 0, None, None)

    points = cache['points']
    plen = len(points)
    if plen == 0:
      return (render['month_key'], task, 0, cache['min_label'], cache['max_label'])

    return (
      render['month_key'],
      task,
      plen,
      cache['min_label'],
      cache['max_label'],
      points[0][1],
      points[-1][1]
    )

  def _start_graph_anim(self, start = 0, end = 1, duration = 380):
    self.graph_anim = anm.anm_object(duration, {
      'morph': [anm.ease_out, start, end]
    })
    self.graph_anim.goal = 1
    self.seq.register('graph', self.graph_anim)
    
    self._mark_dirty()

  def _graph_animating(self):
    obj = self.seq.get_obj('graph')
    return not obj.get_time == 1.0

  def _graph_morph(self):
    if self.graph_anim is None:
      return 1.0
    return clamp01(self.graph_anim.morph)

  def _month_date_from_offset(self, offset):
    year = self.shifted_day[0]
    month = self.shifted_day[1] + offset
    while month < 1:
      year -= 1
      month += 12
    while month > 12:
      year += 1
      month -= 12
    return (year, month, 1)

  def _refresh_current_render(self, animate_graph = False):
    prev_sig = None
    if animate_graph:
      prev_sig = self._graph_signature(self.current_render)
    month_key = iso_month_key(self.shifted_day)
    cur_task = self.cur_n_task_by_month.get(month_key)
    self.current_render = self.cache.get_render(self.shifted_day, cur_task)
    self.cur_n_task_by_month[month_key] = self.current_render['cur_n_task']
    self._sync_achievement_scroll(month_key, len(self.current_render['task_rows']), self.achievement_scroll_anim_month != month_key)
    if animate_graph:
      new_sig = self._graph_signature(self.current_render)
      if new_sig != prev_sig and self.current_render['cur_n_task'] is not None:
        self._start_graph_anim(0, 1, 380)
    self._mark_dirty()

  def _refresh_prev_render(self):
    if self.prev_render is None or self.cache is None:
      return
    year = int(self.prev_render['month_key'][0:4])
    month = int(self.prev_render['month_key'][5:7])
    d = (year, month, 1)
    cur_task = self.cur_n_task_by_month.get(self.prev_render['month_key'])
    self.prev_render = self.cache.get_render(d, cur_task)
    self.cur_n_task_by_month[self.prev_render['month_key']] = self.prev_render['cur_n_task']
    self._sync_achievement_scroll(self.prev_render['month_key'], len(self.prev_render['task_rows']), True)

  def open_files(self, filename):
    self.org_filename = filename
    self.cache = JournalCache(filename)
    self.achievement_scroll_by_month = {}
    self.achievement_scroll_anim = 0.0
    self.achievement_scroll_anim_month = None
    self.last_achievement_slider = 255
    if len(self.cache.filenames) == 0:
      return False
    self._refresh_current_render(True)
    return True

  def _apply_loading_updates(self):
    if self.cache is None:
      return
    changed = self.cache.step(160, 18)
    if len(changed) > 0:
      current_key = iso_month_key(self.shifted_day)
      if current_key in changed:
        self._refresh_current_render(True)
      if self.prev_render and self.prev_render['month_key'] in changed:
        self._refresh_prev_render()
        self._mark_dirty()

    if self.auto_follow_latest and (not self.user_navigated) and self.cache.done and self.cache.latest_date:
      latest_month = first_of_month(self.cache.latest_date)
      if latest_month != self.shifted_day:
        self.shifted_day = latest_month
        self._refresh_current_render(True)

  def _switch_month(self, offset):
    if self.cache is None:
      return
    self.user_navigated = True
    self.auto_follow_latest = False
    self.prev_render = self.current_render
    self.shifted_day = self._month_date_from_offset(offset)
    self._refresh_current_render(True)
    self.slide_dir = offset
    slide_start = self.height if offset > 0 else -self.height
    self._start_panel_anim(slide_start, 0, 0, 1, 120)
    obj = self.seq.get_obj('chart_dither')
    obj.seek(0)

  def _select_prev_numeric_task(self):
    keys = self.current_render['graph_task_keys']
    cur = self.current_render['cur_n_task']
    if not cur or len(keys) == 0:
      return
    prev = None
    for key in keys:
      if key == cur:
        break
      prev = key
    if prev is not None:
      self.cur_n_task_by_month[self.current_render['month_key']] = prev
      self._refresh_current_render(True)

  def _select_next_numeric_task(self):
    keys = self.current_render['graph_task_keys']
    cur = self.current_render['cur_n_task']
    if not cur or len(keys) == 0:
      return
    for i, key in enumerate(keys):
      if key == cur and i + 1 < len(keys):
        nxt = keys[i + 1]
        self.cur_n_task_by_month[self.current_render['month_key']] = nxt
        self._refresh_current_render(True)
        break

  def _draw_month_title(self, render, yoff):
    self.v.set_draw_color(1)
    self.v.set_font('u8g2_font_profont29_mf')
    self.v.draw_str(self.goffset[0] + 10 , self.goffset[1] + 30 + yoff, render['month_title'])

  def _draw_mouse_overlay(self, col, yoff):
    x = col * 10 + 85
    y = yoff
    self.v.set_draw_color(1)
    self.v.set_font('u8g2_font_profont15_mf')
    self.v.draw_str(x + 3, 16+y, '%d' % (col + 1))
    self.v.set_dither(10)
    self.v.draw_line(x, y, x, self.height)
    self.v.set_dither(16)

  def draw_header(self):
    v = self.v
    v.set_draw_color(1)
    v.draw_box(0, 0, 400, 18)
    v.set_draw_color(0)
    v.set_font('u8g2_font_profont15_mf')
    s = 'Journal'
    v.draw_str(4, 14, s)
    v.set_draw_color(1)

  def _draw_tasklist(self, render, yoff, reveal):
    self.v.set_font('u8g2_font_profont15_mf')
    self.v.set_draw_color(1)

    top = self.goffset[1] + 40
    bottom = self.groffset[1]
    visible_rows = self._visible_achievement_rows()
    total_rows = len(render['task_rows'])
    row_pos = self._current_achievement_scroll(render['month_key'], total_rows)
    row_offset = int(row_pos)
    frac = row_pos - row_offset
    y_shift = int(frac * 16)
    extra = 0
    if y_shift > 0 and row_offset + visible_rows < total_rows:
      extra = 1
    visible_task_rows = render['task_rows'][row_offset:row_offset + visible_rows + extra]
    col_limit = int(len(render['month_days']) * reveal + 0.999)
    if col_limit > len(render['month_days']):
      col_limit = len(render['month_days'])

    if total_rows > visible_rows:
      track_x = self.goffset[0] + 390
      track_y = top + yoff
      track_h = visible_rows * 16

      
      self.v.draw_frame(track_x, track_y, 6, track_h)
      max_scroll = total_rows - visible_rows
      knob_h = int((track_h * visible_rows) / total_rows)
      if knob_h < 8:
        knob_h = 8
      knob_y = track_y
      if max_scroll > 0 and track_h > knob_h:
        knob_y += int(((track_h - knob_h) * row_pos) / max_scroll)
      self.v.draw_box(track_x, knob_y, 5, knob_h)


    today_key = iso_date_key((self.year, self.month, self.day))
    current_month = (self.shifted_day[0] == self.year and self.shifted_day[1] == self.month)
    obj = self.seq.get_obj('chart_dither')
    dither = int(obj.dither)
    
    for i, row in enumerate(visible_task_rows):
      boxes = row[1]
      y = top + i * 16 - y_shift + yoff
      if y >= bottom or (y + 16) <= top:
        continue
      task = row[0]
      text_y = y + 14
      if text_y > top and text_y < (bottom + 14):
        self.v.draw_str(self.goffset[0] + 3, text_y + yoff, task)
      for j, box in enumerate(boxes[:col_limit]):
        x = box[0]
        checked = box[1]
        today = current_month and render['month_days'][j][0] == today_key
        if checked:
          self.v.set_dither(dither)
          self.v.draw_box(x, y, 10, 16)
          self.v.set_dither(16)
        else:
          if today:
            self.v.set_dither(4)
            self.v.draw_box(x, y, 10, 16)
            self.v.set_dither(16)
          else:
            self.v.draw_frame(x, y, 10, 16)

    if total_rows > visible_rows:
      self.v.set_draw_color(0)
      self.v.draw_box(0,top-20, 400, 20)
      self.v.draw_box(0,track_y+ track_h,400,20)
      self.v.set_draw_color(1)
    
    for dt, day in render['month_days'][:col_limit]:
      if (day % 5) == 1:
        self.v.draw_str(self.goffset[0] + 70 + day * 10, self.goffset[1] + 35 + yoff, str(day))


  def _draw_graph(self, render, yoff, reveal):
    if len(render['graph_cache']) == 0 or render['cur_n_task'] is None:
      return
    if render['cur_n_task'] not in render['graph_cache']:
      return

    self.v.set_font('u8g2_font_profont15_mf')
    self.v.set_draw_color(1)

    for tx, bx, label, key in render['graph_tabs']:
      self.v.draw_str(tx, yoff + self.groffset[1] + 14, label)
      if render['cur_n_task'] == key:
        self.v.set_draw_color(2)
        self.v.draw_box(bx, yoff + self.groffset[1] + 0, 90, 15)
        self.v.set_draw_color(1)

    cache = render['graph_cache'][render['cur_n_task']]
    self.v.draw_str(self.groffset[0] + 3, yoff + self.groffset[1] + 20 + 60, cache['min_label'])
    self.v.draw_str(self.groffset[0] + 3, self.groffset[1] + 20 + 14 + yoff, cache['max_label'])

    point_limit = int(len(cache['points']) * reveal + 0.999)
    if point_limit > len(cache['points']):
      point_limit = len(cache['points'])
    morph = self._graph_morph()
    base_y = 20 + 30
    last_point = None
    for new_point in cache['points'][:point_limit]:
      px = new_point[0]
      py_local = int(yoff + base_y + (new_point[1] - base_y) * morph)
      py = py_local + self.groffset[1]
      if last_point is not None:
        self.v.set_dither(8)
        self.v.draw_line(last_point[0] + 2, last_point[1] + 2, px + 2, py + 2)
        self.v.set_dither(16)
      self.v.draw_box(px, py, 4, 4)
      last_point = (px, py)

  def _draw_loading(self):
    return

  def _draw_no_data_message(self, yoff):
    self.v.set_draw_color(1)
    self.v.set_font('u8g2_font_profont15_mf')
    self.v.draw_str(110 , 95+yoff, 'No entries for this month yet')

  def _draw_panel(self, render, yoff, reveal, mouse_col = None):
    #self.draw_header()
    if render['has_data']:
      self._draw_tasklist(render, yoff, reveal)
      self._draw_graph(render, yoff, reveal)
    else:
      self._draw_no_data_message(yoff)
    if mouse_col is not None:
      self._draw_mouse_overlay(mouse_col, yoff)
    self._draw_month_title(render, yoff)

  def _handle_achievement_touch(self):
    try:
      keys = self.v.get_tp_keys()
    except Exception:
      self.last_achievement_slider = 255
      return False
    if not keys or len(keys) == 0:
      self.last_achievement_slider = 255
      return False
    return self.handle_achievement_slider(keys[0])

  def draw(self, mouse_active = False, mouse_col = None):
    self.v.clear_buffer()

    if self._panel_animating() and self.prev_render is not None:
      #print('animating')
      slide = int(self.panel_anim.slide)
      reveal = clamp01(self.panel_anim.reveal)
      if self.slide_dir > 0:
        prev_y = slide - self.height
      elif self.slide_dir < 0:
        prev_y = slide + self.height
      else:
        prev_y = 0
      self._draw_panel(self.prev_render, prev_y, 1.0, None)
      overlay_col = mouse_col if mouse_active else None
      self._draw_panel(self.current_render, slide, reveal, overlay_col)
    else:
      overlay_col = mouse_col if mouse_active else None
      reveal = 1.0
      if self.panel_anim is not None:
        reveal = clamp01(self.panel_anim.reveal)
      self._draw_panel(self.current_render, 0, reveal, overlay_col)
      self.prev_render = None
      self.slide_dir = 0


    self._draw_loading()
    self.v.finished()

  def update(self, e):
    if not self.v.active:
      self.v.finished()
      return

    self.update_time()
    self.seq.update(time.ticks_ms())
    self.mouse.update()
    self._apply_loading_updates()
    slider_changed = self._handle_achievement_touch()
    scroll_anim_changed = self._update_achievement_scroll_anim()

    mouse_active = self.mouse.active
    mouse_col = None
    if mouse_active:
      point = self.mouse.get_point()
      mouse_col = point[0] // 10

    progress_bucket = -1
    if self.cache is not None:
      progress_bucket = int(self.cache.progress() * 100)

    animating = False
    for item in self.seq:
      animating = True if item.get_time() != 1.0 else False
      if animating:
        break

    need_redraw = e or slider_changed or scroll_anim_changed or self.dirty or animating
    
    #self._panel_animating() or self._graph_animating() or self._achievement_scroll_animating()
    if mouse_active != self.last_mouse_active:
      need_redraw = True
    if mouse_col != self.last_mouse_col:
      need_redraw = True
    if progress_bucket != self.last_progress_bucket:
      need_redraw = True

    if need_redraw:
      self.draw(mouse_active, mouse_col)
      self.dirty = False
    else:
      self.v.finished()

    self.last_mouse_active = mouse_active
    self.last_mouse_col = mouse_col
    self.last_progress_bucket = progress_bucket

  def _read_key(self):
    keys = self.vs.read(1).encode('ascii')
    if keys != b'\x1b':
      return keys

    seq = [keys]
    seq.append(self.vs.read(1).encode('ascii'))
    if seq[-1] == b'[':
      seq.append(self.vs.read(1).encode('ascii'))
      if seq[-1] >= b'0' and seq[-1] <= b'9':
        seq.append(self.vs.read(1).encode('ascii'))
    return b''.join(seq)

  def keyevent_loop(self):
    while True:
      keys = self._read_key()
      self.key_event = True
      if keys == b'\x1b[A':
        self._switch_month(-1)
      elif keys == b'\x1b[B':
        self._switch_month(1)
      elif keys == b'\x1b[D':
        self._select_prev_numeric_task()
      elif keys == b'\x1b[C':
        self._select_next_numeric_task()
      elif keys == b'r':
        if self.org_filename is not None:
          self.open_files(self.org_filename)
      elif keys == b'q':
        break
      self._mark_dirty()


def run_scan(vs, inputs):
  cache = JournalCache(inputs)
  while not cache.done:
    cache.step(4000, 150)

  print('files: %d' % len(cache.filenames), file = vs)
  print('months: %d' % len(cache.months), file = vs)
  if cache.latest_date is None:
    print('latest: none', file = vs)
    return

  latest_month = first_of_month(cache.latest_date)
  render = cache.get_render(latest_month)
  print('latest: %s' % format_ymd_iso(cache.latest_date), file = vs)
  print('latest_month: %s' % iso_month_key(latest_month), file = vs)
  print('task_rows: %d' % len(render['task_rows']), file = vs)
  print('graph_tasks: %d' % len(render['graph_task_keys']), file = vs)
  if render['cur_n_task']:
    graph = render['graph_cache'][render['cur_n_task']]
    print('selected_graph: %s points:%d min:%s max:%s' % (
      render['cur_n_task'],
      len(graph['points']),
      graph['min_label'],
      graph['max_label']), file = vs)


def main(vs, args):
  scan_only = False
  org_filename = []
  for arg in args[1:]:
    if arg == '--scan':
      scan_only = True
    else:
      org_filename.append(arg)

  if len(org_filename) == 0:
    org_filename = ['/sd/Documents/journal.md']

  if scan_only:
    run_scan(vs, org_filename)
    return

  v = vs.v
  el = elib.esclib()
  obj = graph_diary(vs)

  if not obj.open_files(org_filename):
    print('No matched input files', file = vs)
    return

  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))
  v.callback(obj.update)
  try:
    obj.keyevent_loop()
  finally:
    v.print(el.display_mode(True))
    v.callback(None)
    pass
