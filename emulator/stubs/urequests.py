# urequests stub — HTTP calls return empty responses (no network in emulator)

class Response:
  def __init__(self):
    self.status_code = 0
    self.text = ''
    self.content = b''
  def json(self): return {}
  def close(self): pass

def get(url, **kw): return Response()
def post(url, **kw): return Response()
def put(url, **kw): return Response()
def delete(url, **kw): return Response()
def request(*a, **kw): return Response()
