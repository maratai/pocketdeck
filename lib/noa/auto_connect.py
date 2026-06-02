import pdeck

def check(vs, silent=False):
  if not pdeck.wifi_connected():
    if not silent:
      print("No WiFi connection, connecting..", file=vs)
    import wifi
    if silent:
      import mock_stream
      stream = mock_stream.mock_stream()
    else:
      stream=vs
    wifi.main(stream, ['wifi', '-b'])
    if not pdeck.wifi_connected():
      return False  
    return True
  else:
    return True

