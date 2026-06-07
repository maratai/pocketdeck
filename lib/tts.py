import gpt_l as gptlib
import argparse
import os
import struct
import wav_play
import audio
import pdeck
import re


def fix_wav_header(filename):
  try:
    size = os.stat(filename)[6]
    if size < 44:
      return False

    data_size = size - 44
    riff_size = size - 8

    with open(filename, 'r+b') as f:
      f.seek(4)
      f.write(struct.pack('<I', riff_size))
      f.seek(40)
      f.write(struct.pack('<I', data_size))
    return True
  except Exception:
    return False


def strip_urls(text):
  # Convert markdown links like [label](https://example.com) -> [label]
  text = re.sub(r'\[([^\]]+)\]\((?:https?|ftp)://[^)\s]+(?:\?[^)]*)?\)', r'[\1]', text)

  # Remove bare URLs
  text = re.sub(r'(?:https?|ftp)://\S+', '', text)

  return text


def play_stream(vs, stream):
  wp = wav_play.wav_play(16000)
  wp.open_stream(stream)
  wp.play()
  while audio.stream_play():
    pdeck.delay_tick(5)
    ret = vs.v.read_nb(1)
    if ret and ret[0] > 0:
      break
  wp.stop()
  wp.close()


def save_stream_and_fix_header(res, filename):
  try:
    with open(filename, 'wb') as f:
      while True:
        chunk = res.raw.read(1024)
        if not chunk:
          break
        f.write(chunk)
    return fix_wav_header(filename)
  except Exception:
    return False


def main(vs, args_in):
  parser = argparse.ArgumentParser(
            description='Text to Speech')
  parser.add_argument('input', nargs='?', action='store', default=None,
                      help='Text file to read')
  parser.add_argument('-vm', '--voicemodel', action='store', default='alloy',
                      help='Voice model/type for TTS')
  parser.add_argument('-o', '--output', action='store', default=None,
                      help='Output WAV filename. Default is streaming playback only')

  args = parser.parse_args(args_in[1:])

  if not args.input:
    print('Specify input text file', file=vs)
    return

  try:
    with open(args.input, 'r') as f:
      text = f.read()
  except Exception:
    print('Failed to open input file', file=vs)
    return

  text = strip_urls(text)

  gpt = gptlib.chatgpt_util(vs)
  if not gpt.read_api_key():
    print('Set OpenAI key in /config/openai_api_key', file=vs)
    return

  print('Generating speech...', file=vs)
  res = gpt.tts_stream(text, voice=args.voicemodel)
  if not res or res.status_code != 200:
    print(f'TTS failed', file=vs)
    try:
      if res:
        res.close()
    except Exception:
      pass
    return

  if args.output:
    print('Saving to {}...'.format(args.output), file=vs)
    ok = save_stream_and_fix_header(res, args.output)
    res.close()
    if not ok:
      print('Failed to save or fix WAV header', file=vs)
      return
    print('Saved to {}'.format(args.output), file=vs)
  else:
    print('Streaming audio... press any key to stop', file=vs)
    try:
      stream = getattr(res, 'raw', getattr(res, 's', res))
      play_stream(vs, stream)
    finally:
      res.close()
