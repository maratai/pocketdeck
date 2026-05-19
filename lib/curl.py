import sys
import argparse
import socket
import ssl

_VERSION = "Pocket Deck curl 0.1"

def print_vs(vs, s=""):
  try:
    vs.write(str(s) + "\n")
  except Exception:
    print(s)

def _split_url(url):
  scheme = "http"
  rest = url

  p = url.find("://")
  if p >= 0:
    scheme = url[:p].lower()
    rest = url[p + 3:]

  slash = rest.find("/")
  if slash >= 0:
    hostport = rest[:slash]
    path = rest[slash:]
  else:
    hostport = rest
    path = "/"

  if not hostport:
    raise ValueError("URL has no host")

  host = hostport
  port = 443 if scheme == "https" else 80

  # Basic IPv6 bracket form is not supported in this tiny clone.
  colon = hostport.rfind(":")
  if colon > 0:
    port_s = hostport[colon + 1:]
    if port_s:
      try:
        port = int(port_s)
        host = hostport[:colon]
      except Exception:
        host = hostport

  if scheme != "http" and scheme != "https":
    raise ValueError("Unsupported scheme: " + scheme)

  return scheme, host, port, path

def _parse_header_line(line):
  p = line.find(":")
  if p <= 0:
    raise ValueError("Bad header, expected 'Name: value': " + line)
  name = line[:p].strip()
  value = line[p + 1:].strip()
  if not name:
    raise ValueError("Empty header name")
  return name, value

def _read_all(sock, chunk_size=1024):
  out = b""
  while True:
    try:
      b = sock.read(chunk_size)
    except AttributeError:
      b = sock.recv(chunk_size)
    if not b:
      break
    out += b
  return out

def _find_header_end(data):
  p = data.find(b"\r\n\r\n")
  if p >= 0:
    return p, 4
  p = data.find(b"\n\n")
  if p >= 0:
    return p, 2
  return -1, 0

def _decode_chunked(body):
  pos = 0
  out = b""

  while True:
    line_end = body.find(b"\r\n", pos)
    sep_len = 2
    if line_end < 0:
      line_end = body.find(b"\n", pos)
      sep_len = 1
    if line_end < 0:
      break

    line = body[pos:line_end]
    semi = line.find(b";")
    if semi >= 0:
      line = line[:semi]

    try:
      size = int(line.strip(), 16)
    except Exception:
      break

    pos = line_end + sep_len
    if size == 0:
      break

    out += body[pos:pos + size]
    pos += size

    if body[pos:pos + 2] == b"\r\n":
      pos += 2
    elif body[pos:pos + 1] == b"\n":
      pos += 1

  return out

def _headers_to_dict(header_text):
  lines = header_text.split("\n")
  status = lines[0].strip() if lines else ""
  headers = {}

  for line in lines[1:]:
    line = line.strip()
    if not line:
      continue
    p = line.find(":")
    if p > 0:
      k = line[:p].strip().lower()
      v = line[p + 1:].strip()
      headers[k] = v

  return status, headers

def _arg_get(args, names, default=None):
  # Depending on option spelling, values are stored under the option name.
  # This helper keeps the call site robust for short/long option names.
  for name in names:
    try:
      return getattr(args, name)
    except Exception:
      pass

  try:
    d = args.__dict__
    for name in names:
      if name in d:
        return d[name]
  except Exception:
    pass

  return default

def request(url, method="GET", data=None, header_lines=None,
            user_agent="pdeck-curl/0.1"):
  scheme, host, port, path = _split_url(url)

  method = method.upper()
  if data is None:
    data_b = b""
  elif isinstance(data, bytes):
    data_b = data
  else:
    data_b = str(data).encode("utf-8")

  headers = {}
  headers["Host"] = host
  headers["User-Agent"] = user_agent
  headers["Connection"] = "close"
  headers["Accept"] = "*/*"

  if header_lines:
    for h in header_lines:
      name, value = _parse_header_line(h)
      headers[name] = value

  if method == "POST" or len(data_b) > 0:
    headers["Content-Length"] = str(len(data_b))
    has_ct = False
    for k in headers:
      if k.lower() == "content-type":
        has_ct = True
        break
    if not has_ct:
      headers["Content-Type"] = "application/x-www-form-urlencoded"

  req = method + " " + path + " HTTP/1.1\r\n"
  for k in headers:
    req += k + ": " + headers[k] + "\r\n"
  req += "\r\n"

  addr = socket.getaddrinfo(host, port)[0][-1]
  s = socket.socket()
  try:
    s.connect(addr)
    if scheme == "https":
      try:
        s = ssl.wrap_socket(s, server_hostname=host)
      except TypeError:
        s = ssl.wrap_socket(s)

    s.write(req.encode("utf-8"))
    if len(data_b) > 0:
      s.write(data_b)

    raw = _read_all(s)
  finally:
    try:
      s.close()
    except Exception:
      pass

  hpos, hlen = _find_header_end(raw)
  if hpos < 0:
    return "", {}, raw

  header_b = raw[:hpos]
  body = raw[hpos + hlen:]

  try:
    header_text = header_b.decode("utf-8")
  except Exception:
    header_text = header_b.decode()

  status, resp_headers = _headers_to_dict(header_text)

  te = resp_headers.get("transfer-encoding", "")
  if te.lower().find("chunked") >= 0:
    body = _decode_chunked(body)

  return status, resp_headers, body

def build_parser():
  parser = argparse.ArgumentParser(
    description="Tiny curl clone for Pocket Deck"
  )
  #parser.add_argument("url", nargs="?", help="URL to request, http:// or https://")
  parser.add_argument("-o", "--output",
                      default=None, help="Write body to file")
  parser.add_argument("-X", "--request",
                      default="GET", help="HTTP method, e.g. GET or POST")
  parser.add_argument("-H", "--header",
                      default=None,
                      nargs='*',
                      help="Custom header, e.g. -H 'Accept: application/json'")
  parser.add_argument("-d", "--data",
                      default=None, help="Request body data")
  parser.add_argument("-i", "--include", action="store_true",
                      help="Include response status and headers in output")
  parser.add_argument("-s", "--silent", action="store_true",
                      help="Silent mode, suppress progress/status messages")
  parser.add_argument("-V", "--version", action="store_true",
                      help="Show version")
  return parser

def _write_body_to_vs(vs, body):
  try:
    text = body.decode("utf-8")
    vs.write(text)
    if not text.endswith("\n"):
      vs.write("\n")
  except Exception:
    # Binary fallback: print compact hex-ish repr instead of crashing terminal.
    print_vs(vs, body)

def main(vs, args_in):
  parser = build_parser()
  try:
    print(args_in)
    url=None
    if len(args_in) > 1:
      url = args_in[-1]
    args_in=args_in[:-1]
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return 2

  version = _arg_get(args, ("version", "V"), False)
  #url = _arg_get(args, ("url",), None)
  output = _arg_get(args, ("output", "o"), None)
  request_method = _arg_get(args, ("request", "X"), "GET")
  #headers = []
  headers = _arg_get(args, ("header", "H"), [])
  #if header:
  #  headers = [header]
  data = _arg_get(args, ("data", "d"), None)
  include_headers = _arg_get(args, ("include", "i"), False)
  silent = _arg_get(args, ("silent", "s"), False)

  if version:
    print_vs(vs, _VERSION)
    return 0

  if not url:
    print_vs(vs, "curl: URL required")
    print_vs(vs, "Try: curl https://example.com")
    return 2

  method = request_method
  if data is not None and method == "GET":
    method = "POST"

  try:
    status, headers, body = request(
      url,
      method=method,
      data=data,
      header_lines=headers
    )
  except Exception as e:
    print_vs(vs, "curl: error: " + str(e))
    return 1

  if output:
    try:
      with open(output, "wb") as f:
        f.write(body)
      if not silent:
        print_vs(vs, "Saved " + str(len(body)) + " bytes to " + output)
    except Exception as e:
      print_vs(vs, "curl: cannot write output: " + str(e))
      return 1
  else:
    if include_headers:
      print_vs(vs, status)
      for k in headers:
        print_vs(vs, k + ": " + headers[k])
      print_vs(vs, "")
    _write_body_to_vs(vs, body)

  if not silent and status:
    print_vs(vs, "")
    print_vs(vs, status)

  return 0
