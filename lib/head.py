import argparse


def _head_file(vs, path, n):
  try:
    with open(path, 'r') as f:
      count = 0
      for line in f:
        print(line.rstrip('\n'), file=vs)
        count += 1
        if count >= n:
          break
  except OSError as e:
    print('head: cannot open {}: {}'.format(path, e), file=vs)
    return 1
  return 0


def main(vs, args_in):
  parser = argparse.ArgumentParser(description='print first lines of files')
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
    _head_file(vs, path, args.n)
    first = False
