#!/usr/bin/env python3
# Build lib/apps_db.json from docs/README.md.
#
# Two sources in README.md:
#   1. `command | summary` Markdown tables (Command Shell section)
#   2. ### per-app sections under "Basic applications"
#
# Heuristics are deliberately loose — a parallel hand-edited
# lib/apps_db_overrides.json is merged on top so unparseable entries can be
# fixed without changing the docs.

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs', 'README.md')
OUT = os.path.join(ROOT, 'lib/data', 'apps_db.json')
OVERRIDES = os.path.join(ROOT, 'lib/data', 'apps_db_overrides.json')

# Tokens like `-r`, `-X`, `--include`. We keep short single-letter flags only;
# long flags are rarer and harder to disambiguate from prose.
FLAG_RE = re.compile(r'(?<![A-Za-z0-9])(-[a-zA-Z])(?![A-Za-z0-9])')

# A command-name token: lowercase letters, digits, underscore. Excludes
# `_ls`/`_rm` etc. by the leading-underscore filter below.
NAME_RE = re.compile(r'^[a-z][a-z0-9_]*$')

# `[filename]`, `[file]`, `file_name`, etc. in code blocks/inline code.
FILE_HINTS = ('filename', 'file_name', '[file', '[path', 'wav_file', 'file',
              'book_filename', 'board_file', '<local>','src','dst','dir_name','[dir')


def parse_table_rows(lines, start_idx):
  """Read a Markdown table starting near start_idx; yield (name, summary)."""
  i = start_idx
  while i < len(lines) and '|' not in lines[i]:
    i += 1
  if i >= len(lines):
    return
  # Skip header + separator
  i += 2
  while i < len(lines) and '|' in lines[i]:
    row = lines[i].split('|', 1)
    name_part = row[0].strip()
    summary = row[1].strip() if len(row) > 1 else ''
    # Skip "or"-style alternatives — take first plain token.
    name_tokens = re.split(r'\s+', name_part)
    name = name_tokens[0]
    name_args = name_tokens[1:]
    if NAME_RE.match(name):
      yield name, name_args, summary
    i += 1


def first_backticked(text):
  m = re.search(r'`([a-z][a-z0-9_]*)`', text)
  return m.group(1) if m else None


def first_sentence(text):
  text = text.strip()
  m = re.search(r'[.!?](\s|$)', text)
  return text[:m.start() + 1] if m else text


def extract_section_app(name_from_heading, body):
  """Given a `### name` section body, return (cmd_name, info) or None."""
  cmd = first_backticked(body) or (name_from_heading
                                    if NAME_RE.match(name_from_heading) else None)
  if cmd is None:
    return None
  # Summary: first non-empty line that isn't a code fence/list bullet.
  summary = ''
  for line in body.splitlines():
    s = line.strip()
    if not s or s.startswith('```') or s.startswith('-') or s.startswith('#'):
      continue
    summary = first_sentence(s)
    # Strip the leading "`name` is " when present so summaries read cleanly.
    summary = re.sub(r'^`?[a-z_][a-z0-9_]*`?\s+(is|are)\s+', '', summary,
                     count=1)
    break
  flags = sorted(set(FLAG_RE.findall(body)))
  low = body.lower()
  takes_file = any(h in low for h in FILE_HINTS)
  return cmd, {
      'summary': summary,
      'flags': flags,
      'takes_file': takes_file,
  }


def parse(md):
  apps = {}
  lines = md.splitlines()

  # Tables in "Command Shell" section.
  for i, line in enumerate(lines):
    if line.startswith('command | summary'):
      for name, name_args, summary in parse_table_rows(lines, i):
        #print(summary)
        apps[name] = {
            'summary': summary,
            'flags': sorted(set(FLAG_RE.findall(summary))),
            'takes_file': any(h in ' '.join(name_args).lower() for h in FILE_HINTS),
        }

  # ### per-app sections — only inside "## Basic applications" so we skip
  # hardware sections (USB keyboard, LiPo battery, etc.).
  apps_start = md.find('## Basic applications')
  if apps_start < 0:
    return apps
  next_section = re.search(r'^## ', md[apps_start + 1:], re.MULTILINE)
  apps_end = apps_start + 1 + next_section.start() if next_section else len(md)
  apps_md = md[apps_start:apps_end]

  section_re = re.compile(r'^### +(.+?)\s*$', re.MULTILINE)
  matches = list(section_re.finditer(apps_md))
  for idx, m in enumerate(matches):
    heading = m.group(1).strip()
    name_from_heading = heading.split()[0].lower()
    start = m.end()
    end = matches[idx + 1].start() if idx + 1 < len(matches) else len(apps_md)
    body = apps_md[start:end]
    parsed = extract_section_app(name_from_heading, body)
    if parsed is None:
      continue
    cmd, info = parsed
    # Merge with any existing entry (e.g. from the command table).
    prior = apps.get(cmd, {})
    merged_flags = sorted(set(prior.get('flags', [])) | set(info['flags']))
    apps[cmd] = {
        'summary': info['summary'] or prior.get('summary', ''),
        'flags': merged_flags,
        'takes_file': info['takes_file'] or prior.get('takes_file', False),
    }
  return apps


def main():
  with open(DOCS, 'r') as f:
    md = f.read()
  apps = parse(md)

  if os.path.exists(OVERRIDES):
    with open(OVERRIDES, 'r') as f:
      overrides = json.load(f).get('apps', {})
    for name, ov in overrides.items():
      base = apps.get(name, {'summary': '', 'flags': [], 'takes_file': False})
      base.update(ov)
      apps[name] = base

  out = {'apps': dict(sorted(apps.items()))}
  with open(OUT, 'w') as f:
    json.dump(out, f, separators=(',\n', ': '))
    f.write('\n')
  print('wrote', OUT, 'with', len(apps), 'apps')


if __name__ == '__main__':
  main()
