# Minimal socket shim for the browser emulator.
#
# Raw TCP sockets aren't available inside a Web Worker, but the only socket use in
# the bundled Pocket Deck libs is a single synchronous HTTP/1.0 GET — jp_input's
# google_transliterate(), which calls Google's (CORS-enabled) transliterate
# endpoint to convert hiragana to kanji. We translate that one pattern into the
# worker's synchronous-XHR bridge (emulator_fetch_text) and hand back a fabricated
# HTTP response so the caller's "split on \r\n\r\n then json.loads(body)" keeps
# working unchanged.

AF_INET = 2
SOCK_STREAM = 1


def getaddrinfo(host, port, *a, **k):
  # jp_input takes [0][-1] and uses it as the connect() address.
  return [(AF_INET, SOCK_STREAM, 0, '', (host, port))]


class socket:
  def __init__(self, *a, **k):
    self._host = None
    self._resp = b''
    self._pos = 0

  def connect(self, addr):
    self._host = addr[0]

  def send(self, data):
    if isinstance(data, str):
      data = data.encode('utf-8')
    # Pull the request path out of the "GET <path> HTTP/1.0" request line.
    try:
      line = data.split(b'\r\n', 1)[0].decode('utf-8', 'replace')
      path = line.split(' ', 2)[1]
    except Exception:
      path = '/'
    # Reach the same endpoint over https (CORS-enabled, no mixed-content issues).
    url = 'https://%s%s' % (self._host, path)
    from js import emulator_fetch_text
    body = emulator_fetch_text(url) or ''
    self._resp = (b'HTTP/1.0 200 OK\r\nContent-Type: text/javascript\r\n\r\n'
                  + body.encode('utf-8'))
    self._pos = 0
    return len(data)

  sendall = send

  def recv(self, n):
    chunk = self._resp[self._pos:self._pos + n]
    self._pos += len(chunk)
    return chunk

  def close(self):
    self._resp = b''
    self._pos = 0

  def settimeout(self, *a): pass
  def setsockopt(self, *a): pass
  def setblocking(self, *a): pass
