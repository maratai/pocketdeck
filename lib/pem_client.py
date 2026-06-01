#!/usr/bin/env python3
# pem_client -- open file(s) in an already-running pem instance (PC only),
# emacs-server style.
#
#   pem_client FILE[:LINE[:COL]] ...
#
# The running pem must be a desktop (CPython) build with its open-server active.
# Override the port with PEM_SERVER_PORT (must match the server's).

import os
import socket
import sys

def _parse(arg):
  # Accept FILE, FILE:LINE, or FILE:LINE:COL (only trailing numeric segments).
  segs = arg.rsplit(':', 2)
  if len(segs) == 3 and segs[1].isdigit() and segs[2].isdigit():
    return segs[0], int(segs[1]), int(segs[2])
  segs = arg.rsplit(':', 1)
  if len(segs) == 2 and segs[1].isdigit():
    return segs[0], int(segs[1]), 1
  return arg, 1, 1

def main(argv):
  if len(argv) < 2:
    sys.stderr.write("usage: pem_client FILE[:LINE[:COL]] ...\n")
    return 2
  port = int(os.environ.get('PEM_SERVER_PORT', '51737'))
  rc = 0
  for arg in argv[1:]:
    path, line, col = _parse(arg)
    # Resolve against the client's cwd so the server opens the intended file.
    path = os.path.abspath(os.path.expanduser(path))
    try:
      s = socket.create_connection(('127.0.0.1', port), timeout=2)
      s.sendall("{}\t{}\t{}\n".format(path, line, col).encode('utf-8'))
      s.close()
      print("opened in pem: {} (L{} C{})".format(path, line, col))
    except OSError as e:
      sys.stderr.write(
        "pem server not reachable on 127.0.0.1:{} ({})\n".format(port, e))
      rc = 1
  return rc

if __name__ == '__main__':
  sys.exit(main(sys.argv))
