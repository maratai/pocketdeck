import ujson

def main(vs, args):
  #print("\x1b[?1h", file=vs)
  print("=== Pocket Deck Setup ===", file=vs)
  print("", file=vs)

  print("1. Launch on boot:", file=vs)
  print("   1) Home app (default)", file=vs)
  print("   2) Editor (pem)", file=vs)
  print("> ", file=vs, end='')
  ch = vs.read(1)
  if ch == '2':
    boot_app = 'editor'
    print("Editor", file=vs)
  else:
    boot_app = 'home'
    print("Home app", file=vs)

  print("", file=vs)
  print("2. Enable BLE keyboard? [y/N] ", file=vs)
  ch = vs.read(1)
  if ch in ('y', 'Y'):
    ble_keyboard = True
    print("Yes", file=vs)
  else:
    ble_keyboard = False
    print("No", file=vs)

  print("", file=vs)
  print("3. Connect to internet on boot? [y/N] ", file=vs)
  ch = vs.read(1)
  if ch in ('y', 'Y'):
    wifi_on_boot = True
    print("Yes", file=vs)
  else:
    wifi_on_boot = False
    print("No", file=vs)

  config = {
    'boot_app': boot_app,
    'ble_keyboard': ble_keyboard,
    'wifi_on_boot': wifi_on_boot
  }

  with open('/config/startup.json', 'w') as f:
    f.write(ujson.dumps(config, separators=(',\n', ': ')))

  print("", file=vs)
  print("Saved to /config/startup.json", file=vs)
  print("  Boot app    : " + boot_app, file=vs)
  print("  BLE keyboard: " + str(ble_keyboard), file=vs)
  print("  WiFi on boot: " + str(wifi_on_boot), file=vs)
  print("", file=vs)
  print("Reboot to apply changes.", file=vs)
  #print("\x1b[?1l", file=vs)
