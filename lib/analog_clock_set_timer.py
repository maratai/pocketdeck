import pdeck_utils
import pdeck

def main(vs, args):
  if len(args) != 2:
    print("Usage: analog_clock_set_timer minute", file=vs)
    return
  minute = int(args[1])
  for key in pdeck_utils.app_list:
    
    app=pdeck_utils.app_list[key]
    if app['name'] == 'analog_clock':
      obj = app.get('obj')
      if obj:
        obj.pub_set_timer(minute)
        print("Timer was set successfuly", file=vs)
        pdeck.change_screen(key)
        return
  print("App object not found. Launch the analog_clock app first", file=vs)
  
