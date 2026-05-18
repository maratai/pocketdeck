import asyncio
import websockets
import sys
import hashlib

ESP32_PORT = 12022
WEBSOCKET_PORT = 8000
BUFFER_SIZE = 12000

TCP_CONNECT_TIMEOUT = 5.0
TCP_OP_TIMEOUT = 5.0


async def forward_to_esp32(websocket):
  print(f"Client connected: {websocket.remote_address}")

  tcp_reader = None
  tcp_writer = None

  async def tcp_read_exactly(n):
    return await asyncio.wait_for(tcp_reader.readexactly(n), timeout=TCP_OP_TIMEOUT)

  async def tcp_write(data):
    tcp_writer.write(data)
    await tcp_writer.drain()

  async def read_resp_header():
    header = await tcp_read_exactly(4)
    return header[0]

  async def close_tcp():
    nonlocal tcp_reader, tcp_writer
    if tcp_writer:
      try:
        tcp_writer.close()
        await tcp_writer.wait_closed()
      except Exception:
        pass
    tcp_reader = None
    tcp_writer = None

  try:
    async for message in websocket:
      if isinstance(message, str):
        if message.startswith("target_ip:"):
          new_host = message.split(':', 1)[1]
          try:
            await close_tcp()
            print(f"Connecting to ESP32 at {new_host}:{ESP32_PORT}...")
            tcp_reader, tcp_writer = await asyncio.wait_for(
              asyncio.open_connection(new_host, ESP32_PORT),
              timeout=TCP_CONNECT_TIMEOUT
            )
            print("Connected to ESP32.")
            await websocket.send("connect_success")
          except Exception as e:
            print(f"Connection failed: {e}")
            await close_tcp()
            await websocket.send(f"connect_failed:{e}")
          continue

        if not tcp_writer:
          await websocket.send("ERROR: Not connected to target device.")
          continue

        try:
          if message.startswith("auth:"):
            password = message.split(':', 1)[1]
            md5_hex = hashlib.md5(password.encode('utf-8')).hexdigest()
            await tcp_write(f"auth {md5_hex}".encode('utf-8'))
            code = await read_resp_header()
            if code == 0:
              await websocket.send("auth_success")
              print("Authorization successful.")
            else:
              await websocket.send(f"auth_failed:code_{code}")
              print(f"Authorization failed: code {code}")

          elif message == "send_screen":
            await tcp_write(b"send_screen")
            code = await read_resp_header()
            if code != 0:
              await websocket.send(f"ERROR: Code {code}")
              continue
            data = await tcp_read_exactly(BUFFER_SIZE)
            await websocket.send(data)

          elif message.startswith("put_clipboard:"):
            content = message.split(':', 1)[1].encode('utf-8')
            await tcp_write(b"put_clipboard")
            await tcp_write(len(content).to_bytes(4, 'little'))
            await tcp_write(content)
            code = await read_resp_header()
            if code != 0:
              await websocket.send(f"ERROR: Clipboard put failed ({code})")

          elif message == "get_clipboard":
            await tcp_write(b"get_clipboard")
            code = await read_resp_header()
            if code != 0:
              await websocket.send(f"ERROR: Clipboard get failed ({code})")
              continue
            size_bytes = await tcp_read_exactly(4)
            size = int.from_bytes(size_bytes, 'little')
            clip_data = await tcp_read_exactly(size) if size > 0 else b''
            text = clip_data.decode('utf-8', errors='ignore')
            await websocket.send(f"clipboard_data:{text}")

          elif message == "get_file_list":
            await tcp_write(b"get_file_list")
            code = await read_resp_header()
            if code != 0:
              await websocket.send(f"file_list_error:{code}")
              continue
            size = int.from_bytes(await tcp_read_exactly(4), 'little')
            data = await tcp_read_exactly(size)
            await websocket.send(f"file_list:{data.decode('utf-8')}")

          elif message.startswith("get_file:"):
            filename = message.split(':', 1)[1]
            await tcp_write(f"get_file {filename}".encode('utf-8'))
            code = await read_resp_header()
            if code != 0:
              await websocket.send(f"file_get_error:{code}")
              continue
            size = int.from_bytes(await tcp_read_exactly(4), 'little')
            await websocket.send(f"file_start:{filename}:{size}")
            print(f"Receiving file {filename} ({size} bytes)")
            remaining = size
            while remaining > 0:
              chunk = await asyncio.wait_for(
                tcp_reader.read(min(4096, remaining)),
                timeout=TCP_OP_TIMEOUT
              )
              if not chunk:
                break
              await websocket.send(chunk)
              remaining -= len(chunk)

          else:
            print(f"Unknown string message: {message}")

        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError) as e:
          print(f"TCP error: {e}")
          await close_tcp()
          await websocket.send(f"ERROR: {e}")

      elif isinstance(message, bytes):
        if not tcp_writer:
          await websocket.send("ERROR: Not connected to target device.")
          continue

        if message.startswith(b"put_file:"):
          content = message.split(b":", 1)[1]
          f_null_idx = content.find(b"\0")
          if f_null_idx != -1:
            filename = content[:f_null_idx].decode('utf-8')
            file_data = content[f_null_idx+1:]
            try:
              await tcp_write(b"put_file ")
              await tcp_write(filename.encode('utf-8') + b"\0")
              await tcp_write(len(file_data).to_bytes(4, 'little'))
              await tcp_write(file_data)
              code = await read_resp_header()
              if code == 0:
                await websocket.send("file_put_success")
              else:
                await websocket.send(f"file_put_error:{code}")
            except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError) as e:
              print(f"TCP error during put_file: {e}")
              await close_tcp()
              await websocket.send(f"ERROR: {e}")
        else:
          print(f"Unknown binary message: {len(message)} bytes")

  except Exception as e:
    print(f"Connection error: {e}")
    try:
      await websocket.send(f"ERROR: {e}")
    except Exception:
      pass
  finally:
    await close_tcp()
    print(f"Client disconnected: {websocket.remote_address}")


async def main():
  host = sys.argv[1] if len(sys.argv) == 2 else None
  print(f"Starting WebSocket Proxy on port {WEBSOCKET_PORT}")
  async with websockets.serve(forward_to_esp32, "localhost", WEBSOCKET_PORT):
    await asyncio.Future()


if __name__ == "__main__":
  try:
    asyncio.run(main())
  except KeyboardInterrupt:
    print("\nStopping proxy.")
