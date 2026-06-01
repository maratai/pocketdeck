# Font-loader shim for the browser emulator.
#
# On the device, PEM's load_jpfont() loads a CJK bitmap font into the terminal.
# The emulator renders Japanese with the host browser's own CJK font (see the
# terminal renderer in index.html), so loading a device font is a no-op here.
# We only need to satisfy the surface PEM touches: load() and font_list[name].

font_list = {}


def load(path):
  font_list.setdefault(path, b'')
  return font_list[path]


def file_exists(name):
  return False
