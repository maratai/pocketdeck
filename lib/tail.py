import argparse


def _tail_file(vs, path, n):
  try:
    with open(path, 'r') as f:
      buf = []
      for line in f:
        if len(buf) >= n:
          buf.pop(0)
        buf.append(line.rstrip('\n'))
  except OSError as e:
    print('tail: cannot open {}: {}'.format(path, e), file=vs)
    return 1

  for line in buf:
    print(line, file=vs)
  return 0


def main(vs, args_in):
  parser = argparse.ArgumentParser(description='print last lines of files')
  parser.add_argument('-n', type=int, default=10, help='number of lines')
  parser.add_argument('files', nargs='+', help='file paths')

  try:
    args = parser.parse_args(args_in[1:])
  except SystemExit:
    return

  first = True
  for path in args.files:
    if len(args.files) > 1:
      if not first:
        print('', file=vs)
      print('==> {} <=='.format(path), file=vs)
    _tail_file(vs, path, args.n)
    first = False
