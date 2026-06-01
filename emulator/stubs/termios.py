# Minimal no-op termios for the browser emulator.
TCSANOW = 0; TCSADRAIN = 1; TCSAFLUSH = 2
ECHO = 8; ICANON = 256; VMIN = 6; VTIME = 5
def tcgetattr(fd): return [0,0,0,0,0,0,[0]*32]
def tcsetattr(fd, when, attrs): pass
def setraw(fd, when=0): pass
def setcbreak(fd, when=0): pass
