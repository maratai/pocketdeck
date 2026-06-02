# wav_loader stub — audio not supported in emulator; return empty buffers
import array

def load_wav(filename, sample_rate=None, channels=None):
  if channels is None:
    channels = 2
  return (array.array('h'), channels)

class WavLoader:
  def __init__(self): pass
  def open(self, f): return self
  def load_all(self, f, **kw): return array.array('h')
  def load_frames(self, f, **kw): return []
