import pdeck_utils
import pdeck

def _parse(arg):
  # Accept FILE, FILE:LINE, or FILE:LINE:COL (only trailing numeric segments).
  # Matches the pem_client colon syntax so both share one format.
  segs = arg.rsplit(':', 2)
  if len(segs) == 3 and segs[1].isdigit() and segs[2].isdigit():
    return segs[0], int(segs[1]), int(segs[2])
  segs = arg.rsplit(':', 1)
  if len(segs) == 2 and segs[1].isdigit():
    return segs[0], int(segs[1]), 1
  return arg, 1, 1

def main(vs, args):
  # Open a file in an already-running pem editor (emacs-server style). Mirrors
  # analog_clock_set_timer: find the running app by name in pdeck_utils.app_list,
  # grab the registered editor object, queue the open, then switch to its screen.
  if len(args) < 2:
    print("Usage: pem_open FILE[:LINE[:COL]]  |  FILE LINE [COL]", file=vs)
    return
  filename, linenum, colnum = _parse(args[1])
  # Separate-arg form still works too: pem_open FILE LINE [COL].
  if len(args) > 2 and args[2].isdigit():
    linenum = int(args[2])
    colnum = int(args[3]) if len(args) > 3 and args[3].isdigit() else 1
  for key in pdeck_utils.app_list:
    app = pdeck_utils.app_list[key]
    if app['name'] == 'pem':
      obj = app.get('obj')
      if obj:
        obj.pub_open_file(filename, linenum, colnum)
        print("File open requested", file=vs)
        pdeck.change_screen(key)
        return
  print("App object not found. Launch the pem app first", file=vs)
