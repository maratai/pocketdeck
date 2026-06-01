STA_IF = 0
AP_IF = 1
class WLAN:
  def __init__(self, *a): self._c = False
  def active(self, v=None): return self._c if v is None else None
  def connect(self, *a, **k): pass
  def disconnect(self): pass
  def isconnected(self): return True   # the browser host is effectively online
  def ifconfig(self, *a): return ('0.0.0.0','0.0.0.0','0.0.0.0','0.0.0.0')
  def scan(self): return []
  def status(self, *a): return 0
  def config(self, *a, **k): return ''
