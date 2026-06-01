# Minimal micropython module stub for CPython/Pyodide.
def const(x): return x
def native(f): return f
def viper(f): return f
def asm_thumb(f): return f
def alloc_emergency_exception_buf(n): pass
def mem_info(*a): pass
def qstr_info(*a): pass
def kbd_intr(n): pass
def schedule(fn, arg=None):
  try: fn(arg)
  except Exception: pass
def opt_level(*a): return 0
