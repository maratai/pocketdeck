import array
import struct
import math

import struct
import dsplib as dl

class glyph_2d:
  def __init__(self, num_faces, num_verts, uni_verts_2d, indices, advance=0):
    self.num_faces = num_faces
    self.num_verts = num_verts
    self.uni_verts = uni_verts_2d  # array.array('f') (X, Y only)
    self.indices = indices         # array.array('H')
    self.advance = advance         # uint16
    
    # Pre-allocate scratchpads for dsplib 2D
    self.out_poly = array.array('h', [0] * (num_faces * 6))
    self.out_dither = array.array('b', [16] * num_faces)
    self.t_verts = array.array('f', [0.0] * (num_verts * 2))
    self.colors = array.array('f', [16.0] * num_verts) # Solid white vertex colors
    self.face_indices = array.array('H', range(num_faces))

class font_2d:
  def __init__(self, filename):
    self.filename = filename
    self.glyphs = {} # ID -> offset
    self.advances = {}
    self.legacy_mode = False
    self._glyph_cache = {}
    self._load_header()


  def _load_header(self):
    try:
      with open(self.filename, 'rb') as f:
        header = f.read(20)
        if len(header) < 20 or header[:4] != b'G3DF':
          print("Error: Invalid G3DF file format.")
          return None

        magic, v1, v2, v3, v4, num_objs, index_off, flags = struct.unpack('<4s4BIII', header)
        
        # Load directory
        f.seek(index_off)
        for _ in range(num_objs):
          entry = f.read(12)
          if len(entry) < 12: break
          cid, off, adv, res = struct.unpack('<IIHH', entry)
          self.glyphs[cid] = off
          self.advances[cid] = adv
          
        print(f"Font2D: Loaded '{self.filename}' with {num_objs} characters.")
    except OSError as e:
      print(f"Font2D Error: Cannot open file '{self.filename}': {e}")
      self.legacy_mode = None
    except Exception as e:
      print(f"Font2D Error parsing header: {e}")
      self.legacy_mode = True

  def get_glyph(self, char):
    if char in self._glyph_cache:
      return self._glyph_cache[char]

    if self.legacy_mode is None:
      return None
      
    cid = ord(char)
    if self.legacy_mode:
      res = self._load_mesh_at(0)
    elif cid not in self.glyphs:
      res = None
    else:
      res = self._load_mesh_at(self.glyphs[cid], self.advances.get(cid, 0))

    self._glyph_cache[char] = res
    return res

  def _load_mesh_at(self, offset, advance=0):
    try:
      with open(self.filename, 'rb') as f:
        f.seek(offset)
        header = f.read(8)
        num_faces, num_verts = struct.unpack('<II', header)
        
        # VERTS (Read 3D, extract 2D)
        verts3 = array.array('f', [0.0] * (num_verts * 3))
        f.readinto(verts3)
        verts2 = array.array('f', [0.0] * (num_verts * 2))
        for i in range(num_verts):
            verts2[i*2] = verts3[i*3]
            verts2[i*2+1] = verts3[i*3+1]
        
        # INDICES
        indices = array.array('H', [0] * (num_faces * 3))
        f.readinto(indices)
        
        return glyph_2d(num_faces, num_verts, verts2, indices, advance)
    except Exception as e:
      print(f"Font2D: Failed to load mesh at {offset}: {e}")
      return None
class text_renderer_2d:
  def __init__(self, font2d, vscreen):
    self.font = font2d
    self.v = vscreen
    self.matrix = array.array('f', [0.0] * 9)
    self.v_pos = array.array('f', [0.0, 0.0])
    self.v_scale = array.array('f', [1.0, 1.0])

  def set_font(self, font):
    self.font = font

  def get_width(self, text, scale):
    total = 0.0
    for ch in text:
      glyph = self.font.get_glyph(ch)
      if glyph:
        total += (glyph.advance / 100.0) * scale
    return total


  def draw_text(self, text, x, y, scale=1.0, rot=0.0, scale_x=None, scale_y=None, light=1.0):
    curr_x = 0.0
    c = math.cos(rot)
    s = math.sin(rot)
    
    if scale_x is None: scale_x = scale
    if scale_y is None: scale_y = scale

    self.v_scale[0] = scale_x
    self.v_scale[1] = -scale_y

    for char in text:
      glyph = self.font.get_glyph(char)
      if glyph is None:
        continue

      adv = (glyph.advance / 100.0) * scale_x
      curr_x += adv / 2.0
      
      if glyph.num_faces > 0:
        # We must pass half-screen dimensions to project_2d for correct culling bounding box (400x240 screen)
        SCREEN_CX = 200.0
        SCREEN_CY = 120.0

        # Rotate the glyph's center position around the string origin
        # And subtract the screen center to compensate for project_2d's automatic centering
        self.v_pos[0] = (x + curr_x * c) - SCREEN_CX
        self.v_pos[1] = (y + curr_x * s) - SCREEN_CY
        
        dl.set_transform_matrix_3x3(self.matrix, rot, self.v_pos, self.v_scale)
        
        # Efficient C-accelerated 2D projection
        dl.project_2d_indexed(
            self.matrix, glyph.uni_verts, glyph.indices, glyph.colors, light,
            glyph.num_faces, glyph.num_verts, int(SCREEN_CX), int(SCREEN_CY), 
            glyph.out_poly, glyph.out_dither, glyph.t_verts
        )
        
        # Blast directly to screen queue
        self.v.draw_2d_faces(glyph.out_poly, glyph.face_indices, glyph.out_dither)
      
      # Advance to next character
      curr_x += adv / 2.0


