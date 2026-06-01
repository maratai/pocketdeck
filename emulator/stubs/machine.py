# Minimal machine stub.
def reset(): pass
def soft_reset(): pass
def freq(*a): return 240000000
def unique_id(): return b'\x00\x00\x00\x00\x00\x00'
class Pin:
  IN=0; OUT=1; PULL_UP=2; PULL_DOWN=3
  def __init__(self,*a,**k): pass
  def value(self,*a):
    return 0
  def on(self): pass
  def off(self): pass
class Timer:
  def __init__(self,*a,**k): pass
  def init(self,*a,**k): pass
  def deinit(self): pass
class RTC:
  def datetime(self,*a): return (2026,1,1,0,0,0,0,0)
# Shared, page-aware I2C memory so read-after-write round-trips work (e.g. the
# audio codec home uses banks via register 0x00, then reads back volume etc.).
_I2C_MEM = {}    # (addr, page, reg) -> bytes
_I2C_PAGE = {}   # addr -> current page (set by writes to register 0x00)
_I2C_RAW = {}    # addr -> last raw bytes (for writeto/readfrom without a register)
_PAGE_REG = 0x00

def _pad(data, n):
  data = bytes(data)
  return data[:n] if len(data) >= n else data + bytes(n - len(data))

class I2C:
  def __init__(self, *a, **k): pass
  def scan(self): return list({a for (a, _, _) in _I2C_MEM} | set(_I2C_RAW))

  def writeto_mem(self, addr, reg, buf, *a, **k):
    if reg == _PAGE_REG:
      _I2C_PAGE[addr] = bytes(buf)[0] if len(buf) else 0
    page = _I2C_PAGE.get(addr, 0)
    _I2C_MEM[(addr, page, reg)] = bytes(buf)
    return 0

  def readfrom_mem(self, addr, reg, n, *a, **k):
    if reg == _PAGE_REG:
      return _pad(bytes([_I2C_PAGE.get(addr, 0)]), n)
    page = _I2C_PAGE.get(addr, 0)
    return _pad(_I2C_MEM.get((addr, page, reg), b''), n)

  def readfrom_mem_into(self, addr, reg, buf, *a, **k):
    data = self.readfrom_mem(addr, reg, len(buf))
    buf[:] = data
    return None

  def writeto(self, addr, buf, *a, **k):
    _I2C_RAW[addr] = bytes(buf)
    return 0

  def readfrom(self, addr, n, *a, **k):
    return _pad(_I2C_RAW.get(addr, b''), n)

  def readfrom_into(self, addr, buf, *a, **k):
    buf[:] = _pad(_I2C_RAW.get(addr, b''), len(buf))
    return None
SoftI2C = I2C
class SPI:
  def __init__(self,*a,**k): pass
  def init(self,*a,**k): pass
  def read(self,n,*a): return bytes(n)
  def write(self,*a,**k): return 0
  def write_readinto(self,*a,**k): return 0
SoftSPI = SPI
class ADC:
  def __init__(self,*a,**k): pass
  def read(self): return 0
  def read_u16(self): return 0
  def atten(self,*a): pass
  def width(self,*a): pass
class PWM:
  def __init__(self,*a,**k): pass
  def freq(self,*a): return 1000
  def duty(self,*a): return 0
  def deinit(self): pass
class I2S:
  RX=0; TX=1; STEREO=2; MONO=1
  def __init__(self,*a,**k): pass
  def init(self,*a,**k): pass
  def readinto(self,buf,*a): return 0
  def write(self,*a,**k): return 0
  def deinit(self): pass
