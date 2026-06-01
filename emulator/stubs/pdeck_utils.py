import sys
import importlib

app_list = {}

def reimport(module_name):
  if module_name in sys.modules:
    del sys.modules[module_name]
  return importlib.import_module(module_name)

def launch(command, screen_num=0):
  pass

timezone = 0

# System helpers we don't emulate (autosleep, priority, etc.) become no-ops.
def __getattr__(name):
  return lambda *a, **kw: None
