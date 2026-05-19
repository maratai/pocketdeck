import os
import io
class IOStream(io.IOBase):
    def __init__(self, filename):
        self.filename = filename
        self.file = open(filename, "w")
        
    def write(self, data):
        self.file.write(data)
        self.file.flush()
        
    def close(self):
        try:
            self.file.close()
        except:
            pass

def createIOStream(filename):
    return IOStream(filename)
