# Audio stub — all no-ops; audio is not supported in the browser emulator.

class _NoopContext:
  def __enter__(self): return self
  def __exit__(self, *a): pass
  def __getattr__(self, name): return lambda *a, **kw: None

def sample_rate(rate=None): return 24000
def wavetable(*a, **kw): return _NoopContext()
def sampler(*a, **kw): return _NoopContext()
def stream(*a, **kw): return _NoopContext()
def router(*a, **kw): return _NoopContext()
def compressor(*a, **kw): return _NoopContext()
def reverb(*a, **kw): return _NoopContext()
def delay(*a, **kw): return _NoopContext()
def filter(*a, **kw): return _NoopContext()

# Any other audio.* call (power, volume, codec setup, …) is a harmless no-op.
def __getattr__(name):
  return lambda *a, **kw: None
