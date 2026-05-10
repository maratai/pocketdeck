import anm
import time
import esclib as elib

class BouncingRBox:
  def __init__(self, v):
    self.v = v
    self.seq = anm.anm_sequencer()
    
    # Simple bouncing animation
    
    # Animation based on Y-axis bouncing
    anim = anm.anm_object(1000, {
        "y": [anm.ease_in_out, 30, 180, 30],
        "scale_y" : [anm.ease_in_out, 1.0, 0.8, 1.0]
    }, loop=True)
    
    self.seq.register("box_y", anim)

    # Another animation based on X-axis bouncing
    anim = anm.anm_object(2500, {
        "x": [lambda t:anm.spring(t, b=4, d=8), 100, 300, 100]
    }, loop=True)
    self.seq.register("box_x", anim)
    

  def update(self, e):
    v = self.v
    t_ms = time.ticks_ms()
    self.seq.update(t_ms)
    
    # Get animated properties
    ay = self.seq.get_obj("box_y")
    ax = self.seq.get_obj("box_x")
    
    
    # Draw animated rbox
    v.set_draw_color(1)
    v.draw_rbox(int(ax.x), int(ay.y), int(80), int(80*ay.scale_y),5)
    
    # Status text
    self.v.set_draw_color(1)
    self.v.draw_box(0, 0, 400, 20)
    v.set_font("u8g2_font_profont15_mf")
    v.set_draw_color(0)
    v.draw_str(5, 14, "Animation example: BOUNCING RBOX")
    v.finished()

def main(vs, args):
  el = elib.esclib()
  v = vs.v
  
  # Screen setup
  v.print(el.erase_screen())
  v.print(el.home())
  v.print(el.display_mode(False)) # Cursor off

  demo = BouncingRBox(v)
  v.callback(demo.update)
  
  try:
    # Wait for user to quit
    while True:
      ret = vs.read(1)
      if ret == 'q':
        break
  finally:
    # Cleanup
    v.callback(None)
    v.print(el.display_mode(True)) # Cursor back on
    print("Demo Finished.", file=vs)
