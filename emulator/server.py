#!/usr/bin/env python3
"""
Dev server for the Pocket Deck browser emulator.
Serves the emulator/ directory on http://localhost:8080
"""
import http.server
import json
import os
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080

class Handler(http.server.SimpleHTTPRequestHandler):
  def end_headers(self):
    # These headers enable SharedArrayBuffer (needed for Pyodide time.sleep in workers).
    # 'credentialless' (unlike 'require-corp') allows CDN resources to load normally.
    self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
    self.send_header('Cross-Origin-Embedder-Policy', 'credentialless')
    self.send_header('Cache-Control', 'no-cache')
    super().end_headers()

  def do_GET(self):
    # Auto-generate _manifest.json from the real files in its folder, so dropping
    # a file into sd_template/Documents makes it appear without editing anything.
    # Also writes the manifest to disk so the committed copy stays in sync for
    # static hosting (GitHub Pages, where no server runs).
    if self.path.split('?')[0].endswith('_manifest.json'):
      rel = self.path.split('?')[0].lstrip('/')
      folder = os.path.dirname(rel)
      if os.path.isdir(folder):
        names = sorted(f for f in os.listdir(folder)
                       if os.path.isfile(os.path.join(folder, f))
                       and not f.startswith('.') and f != '_manifest.json')
        body = json.dumps(names).encode()
        try:
          with open(os.path.join(folder, '_manifest.json'), 'wb') as fh:
            fh.write(body)
        except OSError:
          pass
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return
    super().do_GET()

  def log_message(self, fmt, *args):
    pass  # quiet

if __name__ == '__main__':
  root = os.path.dirname(os.path.abspath(__file__))
  # Serve from the pocketdeck root so ../lib/examples/ paths work
  os.chdir(os.path.join(root, '..'))
  print(f'Pocket Deck Emulator  →  http://localhost:{PORT}/emulator/')
  http.server.test(HandlerClass=Handler, port=PORT, bind='localhost')
