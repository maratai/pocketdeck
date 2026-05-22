import os
import time
import pdeck
import pdeck_utils as pu
import audio
import esclib as elib
import wav_play
import menu_ui
import codec_config
import fontloader
MUSIC_ROOT = "/sd/music"

# Key codes
KEY_UP = b'\x1b[A'
KEY_DOWN = b'\x1b[B'
KEY_RIGHT = b'\x1b[C'
KEY_LEFT = b'\x1b[D'
KEY_ENTER = b'\x0d'
KEY_BS = b'\b'
KEY_SPACE = b' '


class MusicGUI:
  def __init__(self, v, vs):
    self.v = v
    self.vs = vs

    # Playback
    self.wp = wav_play.wav_play(80000)
    self.playing = False
    self.paused = False
    self.current_track_fullpath = None

    self.current_tick = 0

    #fontname = 'u8g2_font_lubR10_te'
    #fontloader.load(fontname)
    #self.song_font = fontloader.font_list[fontname]
    
    self.message = ""
    self.message_life = 0
    self.message_big = ""
    self.message_big_life = 0

    # Audio codec / volume control.
    self.codec = None
    try:
      self.codec = codec_config.codec_config()
    except Exception as e:
      print("codec init error")
      print(e)

    # Slider tracking for volume.
    # 0xff means untouched / no anchor.
    self.slider_start = 0xff
    self.slider_step = 10
    self.volume_step_db = 3

    # Folder navigation.
    # folder_stack stores the current folder path relative to /sd/music.
    # Example: ["artist", "album"] -> /sd/music/artist/album
    self.folder_stack = []

    self.menu_list = []
    self.load_albums()

    self.menu_ui = menu_ui.menu_ui(vs, self.menu_list)

    # menu_ui was originally written for two levels.
    # Extending this list allows deeper navigation without changing menu_ui.py.
    self.menu_ui.y = [0] * 32

  # -------- Data loading ----------
  def _is_dir(self, path):
    try:
      st = os.stat(path)
      return (st[0] & 0x4000) != 0
    except:
      return False

  def _current_folder_path(self):
    path = MUSIC_ROOT
    for name in self.folder_stack:
      path = path + "/" + name
    return path

  def _track_label(self, name):
    # Keep long filenames from overflowing the menu too much.
    if len(name) > 40:
      return name[-40:]
    return name

  def _load_folder_items(self, folder):
    try:
      items = os.listdir(folder)
    except Exception as e:
      self.message = "Cannot open folder"
      self.message_life = 120
      return []

    dirs = []
    tracks = []

    for name in items:
      path = folder + "/" + name
      if self._is_dir(path):
        dirs.append(name)
      else:
        lname = name.lower()
        if lname.endswith(".wav"):
          tracks.append(name)

    dirs.sort(key=lambda s: s.lower())
    tracks.sort(key=lambda s: s.lower())

    menu_items = []

    # Directories are loaded lazily. None means "folder not loaded yet".
    for name in dirs:
      menu_items.append([name, None])

    # WAV files can appear in any folder. Mixed folders are supported.
    for name in tracks:
      menu_items.append([
        self._track_label(name),
        {
          'filename': name,
          'path': folder + "/" + name,
          'type': 'track'
        }
      ])

    return menu_items

  def load_albums(self):
    self.menu_list[:] = self._load_folder_items(MUSIC_ROOT)
    if len(self.menu_list) == 0 and self.message == "":
      self.message = "No music found"
      self.message_life = 120

  # Kept for compatibility with the old single-album code path.
  def load_tracks(self, album):
    folder = MUSIC_ROOT + "/" + album
    items = self._load_folder_items(folder)
    tracks = []
    for item in items:
      if isinstance(item[1], dict) and item[1].get('type') == 'track':
        tracks.append(item)
    return tracks

  # -------- Volume control ----------
  def _get_slider_value(self):
    # Newer firmware may expose get_tp_value(); reference docs expose get_tp_keys().
    # In both cases, the first byte/value is the slider position.
    try:
      tp = self.v.get_tp_value()
      if tp and len(tp) > 0:
        return tp[0]
    except:
      pass

    try:
      tp = self.v.get_tp_keys()
      if tp and len(tp) > 0:
        return tp[0]
    except:
      pass

    return 0xff

  def _raw_volume_to_db(self, raw):
    db = raw - 255
    if db > 0:
      db = 0
    if db < -60:
      db = -60
    return db

  def _db_volume_to_raw(self, db):
    if db > 0:
      db = 0
    if db < -60:
      db = -60
    return 255 + db

  def get_audio_volume(self):
    if not self.codec:
      return 0
    try:
      return self._raw_volume_to_db(self.codec.get_vol())
    except Exception as e:
      print("get volume error")
      print(e)
      return 0

  def set_audio_volume(self, value=None):
    if not self.codec:
      return 0

    # Always acquire the current volume first because other apps may change it.
    try:
      cur = self._raw_volume_to_db(self.codec.get_vol())
    except Exception as e:
      print("get volume error")
      print(e)
      return 0

    if value != None:
      if value > 0:
        value = 0
      if value < -60:
        value = -60

      try:
        self.codec.set_vol(self._db_volume_to_raw(value))
        cur = self._raw_volume_to_db(self.codec.get_vol())
      except Exception as e:
        print("set volume error")
        print(e)

    return cur

  def handle_slider_volume(self):
    slider = self._get_slider_value()

    if slider == 0xff:
      self.slider_start = 0xff
      return

    if self.slider_start == 0xff:
      self.slider_start = slider
      return

    index = 0

    if slider - self.slider_start > self.slider_step:
      index = 1
      self.slider_start += self.slider_step

    if slider - self.slider_start < -self.slider_step:
      index = -1
      self.slider_start -= self.slider_step

    if index == 0:
      return

    # Slider value is 0 at the top and larger lower down.
    # Moving up should make volume louder, moving down should make it quieter.
    cur_db = self.set_audio_volume()
    new_db = cur_db - index * self.volume_step_db
    new_db = self.set_audio_volume(new_db)

    self.message_big = "Volume: " + str(new_db) + " dB"
    self.message_big_life = 80

  # -------- Playback ----------
  def stop(self):
    try:
      self.wp.stop()
      self.wp.close()
    except:
      pass
    self.playing = False
    self.paused = False

  def play_selected(self):
    item = self.menu_ui.get_current_item()[1]
    if not isinstance(item, dict) or item.get('type') != 'track':
      return

    path = item.get('path')
    if not path:
      return

    self.stop()
    try:
      self.wp.open(path)
      self.wp.play()
      self.playing = True
      self.paused = False
      self.current_track_fullpath = path
    except Exception as e:
      print(path)
      print(e)
      self.message = "Play error"
      self.message_life = 120
      self.playing = False
      self.paused = False

  def toggle_pause(self):
    if not self.playing:
      return
    if not self.paused:
      self.wp.stop()
      self.paused = True
    else:
      self.wp.play()
      self.paused = False

  def _current_index(self):
    return self.menu_ui.y[self.menu_ui.depth]

  def _set_current_index(self, idx):
    self.menu_ui.y[self.menu_ui.depth] = idx

  def _is_track_item(self, item):
    if not item or len(item) < 2:
      return False
    detail = item[1]
    return isinstance(detail, dict) and detail.get('type') == 'track'

  def _move_to_track(self, direction):
    root = self.menu_ui.cur_root
    idx = self._current_index() + direction

    while idx >= 0 and idx < len(root):
      if self._is_track_item(root[idx]):
        self._set_current_index(idx)
        return True
      idx += direction

    return False

  def next_track(self):
    if self._move_to_track(1):
      self.play_selected()

  def prev_track(self):
    if self._move_to_track(-1):
      self.play_selected()

  # -------- Drawing ----------
  def _fit_header_text(self, text, max_w):
    original = text
    while len(text) > 0 and self.v.get_str_width(text) > max_w:
      text = text[1:]
    if text != original:
      text = "..." + text
    return text

  def draw_header(self):
    self.v.set_draw_color(0)
    self.v.draw_box(0, 0, 400, 40)
    self.v.set_draw_color(1)

    self.v.set_font('u8g2_font_profont22_mf')

    if self.message_big_life > 0:
      title = self.message_big
      self.message_big_life -= 1
    elif len(self.folder_stack) == 0:
      title = "Music /"
    else:
      title = "Music / " + "/".join(self.folder_stack)

    title = self._fit_header_text(title, 335)
    self.v.draw_str(50, 24, title)

    self.v.set_font('u8g2_font_profont15_mf')
    self.v.set_draw_color(0)
    self.v.draw_box(0, 220, 400, 20)
    self.v.set_draw_color(1)
    self.v.draw_str(10, 238, "Enter: open/play  BS:back  Space:pause  q:quit")

  def draw_play_animation(self, x, y):
    if not self.paused and self.playing:
      pos = ((self.current_tick // 1000) % 1000) // 40
      self.v.draw_box(4, 4, pos, 25)
      self.v.draw_box(8 + pos, 4, 25 - pos, 25)
    else:
      self.v.draw_box(4, 4, 25, 25)

  def draw_message(self):
    if self.message_life <= 0:
      return
    self.v.set_font('u8g2_font_tenfatguys_tf')
    self.v.set_dither(16)
    w = self.v.get_str_width(self.message) + 20
    self.v.draw_box(200, 200, w, 22)
    self.v.set_dither(16)
    self.v.set_draw_color(0)
    self.v.draw_str(210, 216, self.message)
    self.v.set_draw_color(1)
    self.message_life -= 1

  def draw_playbar(self):
    if not self.playing:
      return

    pos, total = self.wp.get_position()
    if total <= 0:
      return

    self.v.set_dither(3)
    self.v.draw_box(10, 100, 15, 100)
    self.v.set_dither(16)

    progress = pos * 100 // total
    if progress < 0:
      progress = 0
    if progress > 100:
      progress = 100

    x = 17
    y = progress + 100
    self.v.set_draw_color(0)
    self.v.draw_disc(x, y, 8, 0xf)
    self.v.set_draw_color(1)
    self.v.draw_circle(x, y, 8, 0xf)
    self.v.draw_circle(x, y, 9, 0xf)

  # -------- Frame update callback ----------
  def update(self, screen_change_requested):
    if not self.v.active:
      self.v.finished()
      return

    self.last_tick = self.current_tick
    self.current_tick = time.ticks_us()
    self.time_diff = self.current_tick - self.last_tick

    self.menu_ui.draw_menu(y_offset=50)
    self.draw_header()
    self.draw_play_animation(0, 0)
    self.menu_ui.draw_cursor(self.time_diff, y_offset=50)
    self.draw_playbar()
    self.draw_message()

    self.v.finished()

  # -------- Input handling ----------
  def read_key(self):
    ret = self.v.read_nb(1)
    if not ret or ret[0] <= 0:
      return None

    k = ret[1].encode('ascii')
    if k == b'\x1b':
      seq = [k]
      seq.append(self.vs.read(1).encode('ascii'))
      if seq[-1] == b'[':
        seq.append(self.vs.read(1).encode('ascii'))
        if seq[-1] >= b'0' and seq[-1] <= b'9':
          seq.append(self.vs.read(1).encode('ascii'))
      return b"".join(seq)

    return k

  def _ensure_menu_depth(self, next_depth):
    while next_depth >= len(self.menu_ui.y):
      self.menu_ui.y.append(0)

  def _update_menu_font(self):
    if self.menu_ui.depth == 0:
      self.menu_ui.change_font("u8g2_font_profont29_mf", 30)
    else:
      #self.menu_ui.change_font(self.song_font, 22)

      self.menu_ui.change_font('u8g2_font_t0_17_me', 17)

  def _open_selected_folder(self):
    item = self.menu_ui.get_current_item()
    name = item[0]
    value = item[1]

    folder_path = self._current_folder_path() + "/" + name

    if value == None:
      child_menu = self._load_folder_items(folder_path)
      if len(child_menu) == 0:
        self.message = "Empty folder"
        self.message_life = 80
        return True

      item[1] = child_menu
      value = child_menu

    if isinstance(value, list):
      self._ensure_menu_depth(self.menu_ui.depth + 1)
      self.folder_stack.append(name)
      self.menu_ui.select_item()
      self._update_menu_font()
      return True

    return False

  def _go_back(self):
    if self.menu_ui.depth == 0:
      return False

    # Preserve old Music app behavior: leaving the current music folder stops playback.
    self.stop()

    if len(self.folder_stack) > 0:
      self.folder_stack.pop()

    self.menu_ui.goup_item()
    self._update_menu_font()
    return True

  def handle_key(self, k):
    # Slider volume works continuously, regardless of keyboard input.
    self.handle_slider_volume()

    if k is None:
      return True

    if k == b'q':
      return False

    if k == KEY_DOWN:
      self.menu_ui.move_cursor(1)
    elif k == KEY_UP:
      self.menu_ui.move_cursor(-1)
    elif k == KEY_BS:
      if not self._go_back():
        return False
    elif k == KEY_RIGHT:
      if self.playing:
        pos, total = self.wp.get_position()
        pos += 60 * self.wp.h_fmt_sampleRate
        if pos < total:
          self.wp.seek(pos)
          self.wp.play()
    elif k == KEY_LEFT:
      if self.playing:
        pos, total = self.wp.get_position()
        pos -= 60 * self.wp.h_fmt_sampleRate
        if pos > 0:
          self.wp.seek(pos)
          self.wp.play()
    elif k == KEY_SPACE:
      self.toggle_pause()
    elif k == KEY_ENTER:
      item = self.menu_ui.get_current_item()[1]
      if item == None or isinstance(item, list):
        self._open_selected_folder()
      elif isinstance(item, dict):
        self.play_selected()

    return True

  def loop(self):
    while True:
      # If track finishes, auto-advance to the next WAV file in the same folder.
      if not self.paused and self.playing and not audio.stream_play():
        self.playing = False
        if self._move_to_track(1):
          self.play_selected()

      k = self.read_key()
      if not self.handle_key(k):
        break

      pdeck.delay_tick(8)

    self.stop()


def main(vs, args):
  v = vs.v

  el = elib.esclib()
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False))

  gui = MusicGUI(v, vs)
  v.callback(gui.update)
  gui.loop()
  v.callback(None)

  v.print(el.display_mode(True))
  print("finished.", file=vs)
