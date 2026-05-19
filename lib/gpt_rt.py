import network, socket, ssl, ubinascii, ujson, urandom, time
import audio, codec_config, pdeck, pdeck_utils as pu
import os, sys, io, _thread
import argparse
import gpt
import gc
import esclib

_el = esclib.esclib()

def load_app_list():
  result = []
  for path in ('/config/apps.json', '/config/agent_apps.json'):
    try:
      with open(path, 'r') as f:
        result += ujson.load(f)
    except:
      pass
  return result

class CaptureStream(io.IOBase):
  _MAX = 3000

  def __init__(self):
    self._parts = []
    self._total = 0

  def write(self, data):
    if isinstance(data, (bytes, bytearray)):
      data = data.decode('utf-8', 'replace')
    remaining = self._MAX - self._total
    if remaining <= 0:
      return
    if len(data) > remaining:
      data = data[:remaining]
    self._parts.append(data)
    self._total += len(data)

  def read(self, n=1):
    return ''

  def getvalue(self):
    return ''.join(self._parts)

def _parse_cmd_string(text):
  parts = []
  cur = ''
  in_quote = False
  quote = ''
  for ch in text:
    if in_quote:
      if ch == quote:
        in_quote = False
      else:
        cur += ch
    else:
      if ch in ('"', "'"):
        in_quote = True
        quote = ch
      elif ch == ' ':
        if cur:
          parts.append(cur)
          cur = ''
      else:
        cur += ch
  if cur:
    parts.append(cur)
  return parts

def load_references(file_list, vs):
  refs = []
  if not file_list:
    return refs
  for name in file_list:
    try:
      with open(name, "r") as f:
        refs.append("---- " + name + " ----\n" + f.read())
    except Exception as e:
      print("Failed to read reference %s: %s" % (name, e), file=vs)
  return refs

def build_session_instructions(model, file_list, references, app_list=None, agent=False):
  ctime = time.gmtime(time.time() + pu.timezone * 60 * 15)
  text = (
    "You are a helpful AI assistant. Keep your responses brief, conversational, and direct. "
    "You are chatting over a low latency voice link."
    f"[User current time: {ctime[0]:04d}-{ctime[1]:02d}-{ctime[2]:02d} {ctime[3]:02d}:{ctime[4]:02d}]\n"
  )

  if agent:
    text += "\nUse command_with_return to look up information before answering (e.g. list files with 'ls /sd/Documents/word*', read a file with 'cat /path'). Always call it when the user asks about files or device state.\nUse write_file to create or save files on the device filesystem before launching an app that needs them.\n"
    if app_list:
      text += "\nUse launch_app to open apps. Pass optional args (e.g. a file path) to open a specific file. Available apps:\n"
      for item in app_list:
        if isinstance(item, list) and len(item) == 2:
          name = item[0]
          info = item[1]
          desc = info.get('description', '') if isinstance(info, dict) else ''
          text += "  - %s: %s\n" % (name, desc)

  if file_list:
    text += "\n[Attached files: %s]\n" % ", ".join(file_list)

  if references:
    text += "\n\nThe user attached reference files. Use them when answering.\n"
    for i, item in enumerate(references):
      text += "\n----- reference %d -----\n%s\n" % (i, item)

  return text

class SimpleWS:
  def __init__(self, host, path, port=443, headers=None):
    self.sock = socket.socket()
    addr = socket.getaddrinfo(host, port)[0][-1]
    self.sock.connect(addr)

    try:
      self.sock = ssl.wrap_socket(self.sock, server_hostname=host)
    except TypeError:
      self.sock = ssl.wrap_socket(self.sock)
    except Exception:
      try:
        import ussl
        try:
          self.sock = ussl.wrap_socket(self.sock, server_hostname=host)
        except TypeError:
          self.sock = ussl.wrap_socket(self.sock)
      except Exception as e:
        raise Exception("TLS wrap failed: %s" % e)

    key = ubinascii.b2a_base64(bytes([urandom.getrandbits(8) for _ in range(16)])).strip()

    req = "GET %s HTTP/1.1\r\n" % path
    req += "Host: %s\r\n" % host
    req += "Connection: Upgrade\r\n"
    req += "Upgrade: websocket\r\n"
    req += "Sec-WebSocket-Version: 13\r\n"
    req += "Sec-WebSocket-Key: %s\r\n" % key.decode()
    if headers:
      for k in headers:
        req += "%s: %s\r\n" % (k, headers[k])
    req += "\r\n"

    self.sock.write(req.encode())

    l = self.sock.readline()
    if not l or b"101" not in l:
      raise Exception("WebSocket connection failed: " + str(l))
    while True:
      l = self.sock.readline()
      if not l or l == b"\r\n":
        break

    self.sock.setblocking(False)
    self.mask_buf = bytearray(1024)
    self.mask_mv = memoryview(self.mask_buf)

  def _recv_exact(self, n):
    res = bytearray(n)
    view = memoryview(res)
    read = 0
    while read < n:
      try:
        r = self.sock.readinto(view[read:])
        if r is None:
          time.sleep(0.005)
          continue
        if r == 0:
          raise Exception("Socket closed")
        read += r
      except OSError as e:
        if e.args[0] == 11:
          time.sleep(0.005)
          continue
        raise e
    return res

  def recv(self):
    try:
      header = self.sock.read(2)
      if not header:
        return None
    except OSError as e:
      if e.args[0] == 11:
        return None
      raise e
    except Exception as e:
      msg = str(e)
      if "MBEDTLS_ERR_SSL_BAD_INPUT_DATA" in msg:
        return None
      raise e

    if len(header) < 2:
      return None

    b1, b2 = header[0], header[1]
    opcode = b1 & 0x0f

    has_mask = b2 & 0x80
    length = b2 & 0x7f

    if length == 126:
      ext = self._recv_exact(2)
      length = (ext[0] << 8) | ext[1]
    elif length == 127:
      ext = self._recv_exact(8)
      length = 0
      for i in range(8):
        length = (length << 8) | ext[i]

    if has_mask:
      mask = self._recv_exact(4)

    payload = self._recv_exact(length)
    if has_mask:
      for i in range(length):
        payload[i] ^= mask[i % 4]

    if opcode == 8:
      self.sock.close()
      return None

    if opcode == 9:
      self.send(payload, opcode=10)
      return self.recv()

    if opcode == 10:
      return None

    return payload

  def _send_exact(self, data):
    view = memoryview(data)
    written = 0
    length = len(data)
    while written < length:
      try:
        w = self.sock.write(view[written:])
        if w is None:
          time.sleep(0.005)
          continue
        if w == 0:
          raise Exception("Socket closed during write")
        written += w
      except OSError as e:
        if e.args[0] == 11:
          time.sleep(0.005)
          continue
        raise e

  def send(self, data, opcode=1):
    if isinstance(data, str):
      data = data.encode()
    length = len(data)

    header = bytearray(2)
    header[0] = 0x80 | opcode
    mask = bytes([urandom.getrandbits(8) for _ in range(4)])

    if length < 126:
      header[1] = 0x80 | length
      self._send_exact(header)
    elif length < 65536:
      header[1] = 0x80 | 126
      ext = bytearray(2)
      ext[0] = (length >> 8) & 0xff
      ext[1] = length & 0xff
      self._send_exact(header)
      self._send_exact(ext)
    else:
      header[1] = 0x80 | 127
      ext = bytearray(8)
      for i in range(8):
        ext[7-i] = (length >> (i*8)) & 0xff
      self._send_exact(header)
      self._send_exact(ext)

    self._send_exact(mask)

    view = memoryview(data)
    for offset in range(0, length, 1024):
      chunk_len = min(1024, length - offset)
      for i in range(chunk_len):
        self.mask_buf[i] = view[offset + i] ^ mask[(offset + i) % 4]
      self._send_exact(self.mask_mv[:chunk_len])

  def close(self):
    try:
      self.send(b"", opcode=8)
    except:
      pass
    self.sock.close()


class RealtimeAgent:
  def __init__(self, ws, vs, model, file_list, references, app_list=None, agent=False):
    self.ws = ws
    self.vs = vs
    self.model = model
    self.file_list = file_list or []
    self.references = references
    self.app_list = app_list or []
    self.agent = agent
    self.pending_fn_calls = {}
    self.sample_rate = 24000

    self.mic_buf_size = 4000
    self.mic_bufs = [memoryview(bytearray(self.mic_buf_size)), memoryview(bytearray(self.mic_buf_size))]
    self.mic_ready_idx = -1

    self.spk_buf_size = 6000
    self.spk_bufs = [memoryview(bytearray(self.spk_buf_size)), memoryview(bytearray(self.spk_buf_size))]
    self.zero_buf = bytearray(self.spk_buf_size)

    self._audio_lock = _thread.allocate_lock()
    self.audio_queue = []
    self.audio_queue_head = 0
    self.current_play_chunk = bytearray()
    self.current_play_idx = 0
    self.queued_bytes = 0

    self.buffering = True
    self.buffer_threshold = 16000
    self.mute_until = 0
    self.mic_muted = False
    self.vs_active = None
    self.last_play_time = 0

    self.cb_time_max = 0
    self.underrun_count = 0
    self.last_stat_time = time.ticks_ms()

    self.ai_text = ""
    self.ai_text_printed = False
    self.user_text = ""
    self.user_text_partial = ""
    self.user_text_printed = False
    self.agent_executed_text = ""

  def mic_callback(self, index):
    self.mic_ready_idx = index

  def spk_callback(self, index):
    t0 = time.ticks_us()
    dest = self.spk_bufs[index]
    needed = len(dest)
    pos = 0

    if self.buffering:
      if self.queued_bytes >= self.buffer_threshold and time.ticks_diff(time.ticks_ms(), self.mute_until) >= 0:
        self.buffering = False
      else:
        dest[:needed] = self.zero_buf[:needed]
        duration = time.ticks_diff(time.ticks_us(), t0)
        if duration > self.cb_time_max:
          self.cb_time_max = duration
        return

    while needed > 0:
      avail = len(self.current_play_chunk) - self.current_play_idx
      if avail == 0:
        # Try to dequeue next chunk; non-blocking so callback never stalls
        if self._audio_lock.acquire(False):
          has_more = self.audio_queue_head < len(self.audio_queue)
          if has_more:
            self.current_play_chunk = self.audio_queue[self.audio_queue_head]
            self.audio_queue_head += 1
            # Compact list once head advances far enough to avoid unbounded growth
            if self.audio_queue_head >= 8:
              del self.audio_queue[:self.audio_queue_head]
              self.audio_queue_head = 0
            self.current_play_idx = 0
          self._audio_lock.release()
          if not has_more:
            self.buffering = True
            self.underrun_count += 1
            break
          avail = len(self.current_play_chunk)
        else:
          # Main thread holds lock (appending); fill rest with silence this tick
          break

      take = min(avail, needed)
      dest[pos:pos+take] = self.current_play_chunk[self.current_play_idx:self.current_play_idx+take]
      self.current_play_idx += take
      self.queued_bytes -= take
      pos += take
      needed -= take

    if pos < len(dest):
      dest[pos:] = self.zero_buf[:len(dest)-pos]

    if pos > 0:
      self.last_play_time = time.ticks_ms()

    duration = time.ticks_diff(time.ticks_us(), t0)
    if duration > self.cb_time_max:
      self.cb_time_max = duration

  def start(self):
    cc = codec_config.codec_config()
    cc.toggle_li(False)
    cc.set_agc(True)
    cc.set_input_mixer(0x28)

    audio.sample_rate(self.sample_rate)

    num_samples = 0x7FFFFFFF

    audio.stream_setup(0, self.sample_rate, 1, num_samples, self.spk_callback)
    audio.stream_setdata(0, 0, self.spk_bufs[0])
    audio.stream_setdata(0, 1, self.spk_bufs[1])
    audio.stream_play(True)

    audio.stream_setup(1, self.sample_rate, 1, num_samples, self.mic_callback)
    audio.stream_setdata(1, 0, self.mic_bufs[0])
    audio.stream_setdata(1, 1, self.mic_bufs[1])
    audio.stream_record(True)

  def send_session_update(self):
    session = {
      "type": "realtime",
      "instructions": build_session_instructions(self.model, self.file_list, self.references, self.app_list, self.agent),
      "audio": {
        "input": {
          "format": {"type": "audio/pcm", "rate": self.sample_rate},
          "turn_detection": {"type": "server_vad"}
        },
        "output": {
          "format": {"type": "audio/pcm", "rate": self.sample_rate},
          "voice": "marin"
        }
      }
    }
    if self.agent:
      session["tool_choice"] = "auto"
      session["tools"] = [
        {
          "type": "function",
          "name": "command_with_return",
          "description": "Run a text command and return its output. Use to answer questions about files or content. Supported: ls (list files, supports glob patterns like 'word*'), cat (read file), grep (search in files), and curl (get content from web). Detailed usage are stated in README.md..",
          "parameters": {
            "type": "object",
            "properties": {
              "command": {
                "type": "string",
                "description": "Command with arguments, e.g. 'ls /sd/Documents' or 'ls /sd/Documents/word*' or 'cat /sd/notes.txt'"
              }
            },
            "required": ["command"]
          }
        },
        {
          "type": "function",
          "name": "launch_app",
          "description": "Launch a Pocket Deck application by its exact name, optionally passing arguments such as a file path to open",
          "parameters": {
            "type": "object",
            "properties": {
              "app_name": {
                "type": "string",
                "description": "The exact name of the app to launch as listed"
              },
              "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional extra arguments for the app, e.g. a file path like '/sd/test.txt'"
              }
            },
            "required": ["app_name"]
          }
        },
        {
          "type": "function",
          "name": "write_file",
          "description": "Write text content to a file on the device filesystem. Creates or overwrites the file.",
          "parameters": {
            "type": "object",
            "properties": {
              "path": {
                "type": "string",
                "description": "Absolute file path to write to, e.g. '/sd/data/puzzle.txt'"
              },
              "content": {
                "type": "string",
                "description": "Text content to write to the file"
              }
            },
            "required": ["path", "content"]
          }
        }
      ]
    cfg = {"type": "session.update", "session": session}
    self.ws.send(ujson.dumps(cfg))

  def handle_audio_delta(self, msg):
    delta = msg.get("delta")
    if not delta:
      return
    if isinstance(delta, dict):
      audio_b64 = delta.get("audio")
    else:
      audio_b64 = delta
    if audio_b64:
      audio_bytes = ubinascii.a2b_base64(audio_b64)  # decode before acquiring lock
      self._audio_lock.acquire()
      self.audio_queue.append(audio_bytes)
      self.queued_bytes += len(audio_bytes)
      self._audio_lock.release()

  def handle_text_delta(self, msg):
    delta = msg.get("delta")
    if isinstance(delta, str):
      if delta:
        if not self.ai_text_printed:
          print("\nAI: ", file=self.vs)
          self.ai_text_printed = True
        self.ai_text += delta
        self.vs.write(delta)
      return

    if isinstance(delta, dict):
      text = delta.get("text", "")
      if text:
        if not self.ai_text_printed:
          print("\nAI: ", file=self.vs)
          self.ai_text_printed = True
        self.ai_text += text
        self.vs.write(text)

  def handle_user_text_delta(self, text):
    if not text:
      return
    self.user_text_partial += text

  def handle_user_text_completed(self, text):
    if text:
      self.user_text = text
    elif self.user_text_partial:
      self.user_text = self.user_text_partial

  def print_user_text_if_ready(self):
    if self.user_text and not self.user_text_printed:
      print("\nYou: ", file=self.vs)
      self.vs.write(self.user_text)
      self.user_text_printed = True

  def reset_turn_text(self):
    self.ai_text = ""
    self.ai_text_printed = False
    self.user_text = ""
    self.user_text_partial = ""
    self.user_text_printed = False

  def _mute_audio(self, ms):
    self.buffering = True
    self._audio_lock.acquire()
    self.audio_queue = []
    self.audio_queue_head = 0
    self.current_play_chunk = bytearray()
    self.current_play_idx = 0
    self.queued_bytes = 0
    self.mute_until = time.ticks_add(time.ticks_ms(), ms)
    self._audio_lock.release()

  def _search_free_screen(self, launched, scnum=2):
    while True:
      if not pdeck.cmd_exists(scnum) and scnum not in launched:
        return scnum
      scnum += 1
      if scnum == 10:
        return -1

  def execute_command_with_return(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    command = args.get("command", "").strip()
    if not command:
      return "Error: no command specified"
    parts = _parse_cmd_string(command)
    if not parts:
      return "Error: empty command"
    modname = parts[0]
    cap = CaptureStream()
    try:
      exec("import %s" % modname, {})
      sys.modules[modname].main(cap, parts)
    except Exception as e:
      cap.write("Error: %s" % str(e))
    result = cap.getvalue()
    if not result:
      return "(no output)"
    if cap._total >= CaptureStream._MAX:
      result += "\n...(truncated)"
    return result

  def execute_write_file(self, arguments):
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    path = args.get("path", "").strip()
    content = args.get("content", "")
    if not path:
      return "Error: no path specified"
    try:
      backup_msg = ""
      try:
        with open(path, "r") as f:
          existing = f.read()
        t = time.gmtime(time.time() + pu.timezone * 60 * 15)
        filename = path.split("/")[-1]
        backup_name = "%s_%02d%02d_%02d%02d" % (filename, t[1], t[2], t[3], t[4])
        try:
          os.mkdir("/sd/backup")
        except:
          pass
        with open("/sd/backup/" + backup_name, "w") as f:
          f.write(existing)
        backup_msg = " (backup: /sd/backup/%s)" % backup_name
      except OSError:
        pass
      with open(path, "w") as f:
        f.write(content)
      return "Written %d bytes to %s%s" % (len(content), path, backup_msg)
    except Exception as e:
      return "Error: %s" % str(e)

  def execute_function_call(self, call_id, name, arguments):
    if name == "command_with_return":
      return self.execute_command_with_return(arguments)
    if name == "write_file":
      return self.execute_write_file(arguments)
    if name != "launch_app":
      return "Unknown function: %s" % name
    try:
      args = ujson.loads(arguments) if arguments else {}
    except:
      return "Error: invalid arguments"
    app_name = args.get("app_name", "")
    extra_args = args.get("args", [])
    for item in self.app_list:
      if not (isinstance(item, list) and len(item) == 2 and item[0] == app_name):
        continue
      info = item[1]
      if not (isinstance(info, dict) and info.get('type') == 'program'):
        continue
      command = [list(c) for c in info.get('command', [])]
      if extra_args and command:
        command[0] = [command[0][0]] + extra_args
      pref_scnum = info.get('screen_number', None)
      self._mute_audio(3000)
      launched = []
      first = True
      for one in command:
        scnum = self._search_free_screen(launched, pref_scnum if pref_scnum else 2)
        if scnum == -1:
          break
        launched.append(scnum)
        if first:
          pdeck.change_screen(scnum)
          first = False
        pu.launch(one, scnum)
      pdeck.show_screen_num()
      return "Launched %s" % app_name
    return "App not found: %s" % app_name

  def send_function_result(self, call_id, output):
    evt = {
      "type": "conversation.item.create",
      "item": {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output
      }
    }
    self.ws.send(ujson.dumps(evt))
    self.ws.send(ujson.dumps({"type": "response.create"}))

  def process_event(self, msg):
    mtype = msg.get("type", "")
    #print(mtype, file=self.vs)
    if mtype == "response.audio.delta":
      self.handle_text_delta(msg)
    elif mtype == "response.output_audio_transcript.delta":
      #pass
      self.handle_text_delta(msg)
      #print(msg, file=self.vs)
    elif mtype == "response.output_audio_transcript.done":
      pass
      #print(msg, file=self.vs)

    elif mtype == "response.output_audio.delta":
      self.handle_audio_delta(msg)

    elif mtype == "response.text.delta":
      self.handle_text_delta(msg)

    elif mtype == "response.output_text.delta":
      self.handle_text_delta(msg)

    elif mtype == "conversation.item.input_audio_transcription.delta":
      self.handle_user_text_delta(msg.get("delta", ""))

    elif mtype == "conversation.item.input_audio_transcription.completed":
      self.handle_user_text_completed(msg.get("transcript", ""))

    elif mtype == "response.output_item.added":
      item = msg.get("item", {})
      if item.get("type") == "function_call":
        call_id = item.get("call_id", "")
        self.pending_fn_calls[call_id] = {"name": item.get("name", ""), "args": ""}

    elif mtype == "response.function_call_arguments.delta":
      call_id = msg.get("call_id", "")
      if call_id in self.pending_fn_calls:
        self.pending_fn_calls[call_id]["args"] += msg.get("delta", "")

    elif mtype == "response.output_item.done":
      item = msg.get("item", {})
      if item.get("type") == "function_call":
        call_id = item.get("call_id", "")
        fn_name = item.get("name", "")
        arguments = item.get("arguments", "")
        if not arguments and call_id in self.pending_fn_calls:
          arguments = self.pending_fn_calls[call_id].get("args", "")
        print("\n%s[Call]%s %s %s" % (_el.bold(), _el.bold_off(), fn_name, arguments), file=self.vs)
        result = self.execute_function_call(call_id, fn_name, arguments)
        print("%s[Result]%s %s" % (_el.bold(), _el.bold_off(), result), file=self.vs)
        self.send_function_result(call_id, result)
        self.pending_fn_calls.pop(call_id, None)

    elif mtype == "input_audio_buffer.speech_started":
      print("\n%s[User speaking... barge in detected]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
      self.buffering = True  # make callback output silence before we touch shared state
      self._audio_lock.acquire()
      self.audio_queue = []
      self.audio_queue_head = 0
      self.current_play_chunk = bytearray()
      self.current_play_idx = 0
      self.queued_bytes = 0
      self._audio_lock.release()

    elif mtype == "session.updated":
      pass  # print("\n[Session updated]", file=self.vs)

    elif mtype == "response.done":
      self.reset_turn_text()

    elif mtype == "error":
      print("\n%s[Error from server]%s" % (_el.bold(), _el.bold_off()), file=self.vs)
      print(ujson.dumps(msg), file=self.vs)

  def _send_create_response(self, enabled):
    cfg = {
      "type": "session.update",
      "session": {
        "type": "realtime",
        "audio": {
          "input": {
            "turn_detection": {
              "type": "server_vad",
              "create_response": enabled
            }
          }
        }
      }
    }
    self.ws.send(ujson.dumps(cfg))
    pdeck.led(1, 25 if enabled else 0)

  def toggle_mic_mute(self):
    self.mic_muted = not self.mic_muted
    self._send_create_response(not self.mic_muted)
    print("\n%s[Mic %s]%s" % (_el.bold(), "MUTED" if self.mic_muted else "ON", _el.bold_off()), file=self.vs)

  def loop(self):
    active = self.vs.v.active
    if active != self.vs_active:
      self.vs_active = active
      self._send_create_response(active and not self.mic_muted)

    if self.mic_ready_idx != -1:
      idx = self.mic_ready_idx
      self.mic_ready_idx = -1

      if not self.mic_muted and self.vs.v.active:
        if time.ticks_diff(time.ticks_ms(), self.last_play_time) < 400:
          pass
        else:
          mic_data = self.mic_bufs[idx]
          b64 = ubinascii.b2a_base64(mic_data).strip()
          evt = {
            "type": "input_audio_buffer.append",
            "audio": b64.decode()
          }
          self.ws.send(ujson.dumps(evt))

    while True:
      frame = self.ws.recv()
      if not frame:
        break
      try:
        msg = ujson.loads(frame)
        self.process_event(msg)

      except Exception as e:
        print("Message Error:", e, "Frame:", frame[:80], file=self.vs)

    if time.ticks_diff(time.ticks_ms(), self.last_stat_time) > 2000:
      self.cb_time_max = 0
      self.underrun_count = 0
      self.last_stat_time = time.ticks_ms()

    return True

  def terminate(self):
    pdeck.led(1, 0)
    audio.stream_play(False)
    audio.stream_record(False)
    audio.stream_setup(0, 0, 0, 0)
    audio.stream_setup(1, 0, 0, 0)
    self.ws.close()

def main(vs, args_in):
  parser = argparse.ArgumentParser(description='OpenAI Realtime Voice Agent PoC')
  parser.add_argument('-m', '--model', action='store', default='gpt-realtime-2', help='Model to use')
  parser.add_argument('-f', '--file', nargs='+', action='store', help='Attach file(s) as reference')
  parser.add_argument('-a', '--agent', action='store_true', help='Enable agent mode (function calling)')
  args = parser.parse_args(args_in[1:])

  model = args.model
  file_list = args.file or []
  agent = args.agent

  api_key = gpt.read_api_key()
  if not api_key:
    return

  references = []
  if file_list:
    references = load_references(file_list, vs)
    if len(references) > 0:
      print("Loaded %d reference file(s)." % len(references), file=vs)

  app_list = []
  if agent:
    app_list = load_app_list()
    if app_list:
      print("Agent mode: loaded %d app(s)." % len(app_list), file=vs)

  print("Connecting to OpenAI Realtime API using model %s..." % model, file=vs)
  headers = {
    "Authorization": "Bearer %s" % api_key
  }

  try:
    ws = SimpleWS("api.openai.com", "/v1/realtime?model=%s" % model, headers=headers)
    print("Connected!", file=vs)
  except Exception as e:
    print("Failed to connect: %s" % e, file=vs)
    return

  ra = RealtimeAgent(ws, vs, model, file_list, references, app_list, agent)
  print("Starting voice agent%s... Press 'q'/B to quit, Enter to mute/unmute mic." % (" (agent mode)" if agent else ""), file=vs)

  # We don't want gc run for a while
  gc.collect()

  ra.send_session_update()
  ra.start()

  try:
    while True:
      ra.loop()

      ret = vs.v.read_nb(1)
      if ret and ret[0] > 0:
        keys = ret[1].encode('ascii')
        if keys in (b'q', b'\b'):
          print("\nExiting...", file=vs)
          break
        elif keys == b'\r':
          ra.toggle_mic_mute()

      time.sleep(0.005)
  finally:
    ra.terminate()
    

