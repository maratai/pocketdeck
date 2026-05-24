import os
import ujson
import hashlib
import ssh
import pdeck
import auto_connect

import esclib as _esclib

CONFIG_FILE = "/config/sync.json"

_DEFAULT_CONFIG = {
  "password": "",
  "identity": "/config/ssh/id_rsa",
  "remotes": {}
}

# Remote script converts st_mtime to MicroPython Y2K epoch (2000-01-01)
# so both sides use the same epoch and the device can compare directly.
_REMOTE_SCRIPT = (
  "import os,hashlib,json,sys,fnmatch\n"
  "root=sys.argv[1]\n"
  "pattern=sys.argv[2] if len(sys.argv)>2 else None\n"
  "E=946684800\n"
  "r={}\n"
  "if os.path.isdir(root):\n"
  "  for dp,ds,fs in os.walk(root):\n"
  "    for fn in fs:\n"
  "      if pattern and not fnmatch.fnmatch(fn,pattern):continue\n"
  "      p=os.path.join(dp,fn)\n"
  "      rel=os.path.relpath(p,root).replace('\\\\','/')\n"
  "      st=os.stat(p)\n"
  "      r[rel]={'md5':hashlib.md5(open(p,'rb').read()).hexdigest(),'mtime':st.st_mtime-E,'size':st.st_size}\n"
  "print(json.dumps(r))\n"
)


_el = _esclib.esclib()
_RST = "\x1b[0m"

def _b(text):
  return _el.set_font_color(1) + str(text) + _RST

def _p(vs, text):
  vs.write(text + "\n")


def _load_config():
  try:
    with open(CONFIG_FILE, "r") as f:
      return ujson.load(f)
  except OSError:
    cfg = {k: v for k, v in _DEFAULT_CONFIG.items()}
    cfg["remotes"] = {}
    _save_config(cfg)
    return cfg


def _save_config(cfg):
  with open(CONFIG_FILE, "w") as f:
    ujson.dump(cfg, f, separators=(',\n', ': '))


def _md5_file(path):
  h = hashlib.md5()
  with open(path, "rb") as f:
    while True:
      chunk = f.read(4096)
      if not chunk:
        break
      h.update(chunk)
  return "".join(["%02x" % b for b in h.digest()])


def _walk(root, rel=""):
  result = []
  base = root if not rel else root + "/" + rel
  try:
    entries = os.listdir(base)
  except OSError:
    return result
  for name in entries:
    full = base + "/" + name
    rel_name = name if not rel else rel + "/" + name
    st = os.stat(full)
    if st[0] & 0x4000:
      result.extend(_walk(root, rel_name))
    else:
      result.append((rel_name, st))
  return result


def _build_local_manifest(root, pattern=None):
  manifest = {}
  for rel_path, st in _walk(root):
    if pattern:
      basename = rel_path.rsplit('/', 1)[-1] if '/' in rel_path else rel_path
      if not _glob_match(basename, pattern):
        continue
    full = root + "/" + rel_path
    try:
      manifest[rel_path] = {
        "md5": _md5_file(full),
        "mtime": st[8],
        "size": st[6],
      }
    except OSError:
      pass
  return manifest


def _build_remote_manifest(session, remote_root, pattern=None):
  safe_root = remote_root.replace("'", "'\\''")
  safe_pat = (" '" + pattern.replace("'", "'\\''") + "'") if pattern else ""
  cmd = f"python3 - '{safe_root}'{safe_pat} << 'PYEOF'\n{_REMOTE_SCRIPT}PYEOF"
  rc, out = session.exec(cmd)
  if rc != 0 or not out.strip():
    return {}
  try:
    return ujson.loads(out.decode())
  except Exception:
    return {}


def _makedirs_local(path):
  parts = [p for p in path.split("/") if p]
  current = ""
  for part in parts:
    current += "/" + part
    try:
      os.mkdir(current)
    except OSError:
      pass


def _makedirs_remote(session, path):
  safe = path.replace("'", "'\\''")
  session.exec(f"mkdir -p '{safe}'")


def _parent(path):
  idx = path.rfind("/")
  return path[:idx] if idx > 0 else "/"


def _glob_match(name, pattern):
  parts = pattern.split('*')
  if len(parts) == 1:
    return name == pattern
  if not name.startswith(parts[0]):
    return False
  pos = len(parts[0])
  for part in parts[1:-1]:
    idx = name.find(part, pos)
    if idx == -1:
      return False
    pos = idx + len(part)
  last = parts[-1]
  return name.endswith(last) and len(name) >= pos + len(last)


def _sync_pair(session, local_root, remote_root, vs, pattern=None):
  _p(vs, f"  local:  {_b(local_root)}")
  _p(vs, f"  remote: {_b(remote_root)}")

  if pattern:
    _p(vs, f"  filter: {_b(pattern)}")

  _p(vs, "  Scanning local...")
  local = _build_local_manifest(local_root, pattern)
  _p(vs, f"  {_b(len(local))} local files")

  _p(vs, "  Scanning remote...")
  remote = _build_remote_manifest(session, remote_root, pattern)
  _p(vs, f"  {_b(len(remote))} remote files")

  _makedirs_remote(session, remote_root)
  _makedirs_local(local_root)

  pushed = pulled = skipped = errors = 0

  for rel in sorted(set(local.keys()) | set(remote.keys())):
    local_abs = local_root + "/" + rel
    remote_abs = remote_root + "/" + rel
    l = local.get(rel)
    r = remote.get(rel)

    try:
      if l and r:
        if l["md5"] == r["md5"]:
          skipped += 1
          continue
        if r["mtime"] > l["mtime"]:
          _p(vs, f"  [C] {_b('pull')} {rel}")
          _makedirs_local(_parent(local_abs))
          session.get(remote_abs, local_abs)
          pulled += 1
        else:
          _p(vs, f"  [C] {_b('push')} {rel}")
          _makedirs_remote(session, _parent(remote_abs))
          session.put(local_abs, remote_abs)
          pushed += 1
      elif l:
        _p(vs, f"  {_b('push')} {rel}")
        _makedirs_remote(session, _parent(remote_abs))
        session.put(local_abs, remote_abs)
        pushed += 1
      else:
        _p(vs, f"  {_b('pull')} {rel}")
        _makedirs_local(_parent(local_abs))
        session.get(remote_abs, local_abs)
        pulled += 1
    except Exception as e:
      _p(vs, f"  {_b('ERR')} {rel}: {e}")
      errors += 1

  return pushed, pulled, skipped, errors


# --- remote subcommands ---

def _remote_list(vs, cfg):
  remotes = cfg.get("remotes", {})
  if not remotes:
    _p(vs, "No remotes. Use: sync remote add <name> <host> <local> <remote>")
    return
  for name, r in remotes.items():
    _p(vs, f"{name}")
    _p(vs, f"  host:   {r.get('host', '')}")
    _p(vs, f"  local:  {r.get('local', '')}")
    _p(vs, f"  remote: {r.get('remote', '')}")


def _remote_add(vs, cfg, args):
  if len(args) < 4:
    _p(vs, "Usage: sync remote add <name> <host> <local> <remote> [password]")
    _p(vs, "  host example: ryan@192.168.1.10")
    return
  name, host, local, remote = args[0], args[1], args[2].rstrip("/"), args[3].rstrip("/")
  entry = {"host": host, "local": local, "remote": remote}
  if len(args) >= 5:
    entry["password"] = args[4]
  cfg.setdefault("remotes", {})[name] = entry
  _save_config(cfg)
  _p(vs, f"Added remote '{name}'.")


def _remote_remove(vs, cfg, args):
  if not args:
    _p(vs, "Usage: sync remote remove <name>")
    return
  name = args[0]
  remotes = cfg.get("remotes", {})
  if name not in remotes:
    _p(vs, f"Remote '{name}' not found.")
    return
  del remotes[name]
  _save_config(cfg)
  _p(vs, f"Removed remote '{name}'.")


def _cmd_remote(vs, cfg, args):
  if not args or args[0] == "list":
    _remote_list(vs, cfg)
  elif args[0] == "add":
    _remote_add(vs, cfg, args[1:])
  elif args[0] == "remove":
    _remote_remove(vs, cfg, args[1:])
  else:
    _p(vs, f"Unknown: sync remote {args[0]}")
    _p(vs, "Usage: sync remote [add|remove|list]")


def _cmd_exec(vs, cfg, name, pattern=None):
  remotes = cfg.get("remotes", {})
  if name not in remotes:
    _p(vs, f"Remote '{name}' not found.")
    _p(vs, "Run 'sync remote' to list remotes.")
    return

  auto_connect.check(vs)

  r = remotes[name]
  host = r.get("host", "")
  local_root = r.get("local", "").rstrip("/")
  remote_root = r.get("remote", "").rstrip("/")
  password = r.get("password", cfg.get("password", ""))
  identity = cfg.get("identity", "/config/ssh/id_rsa")

  if not host or not local_root or not remote_root:
    _p(vs, f"Remote '{name}' has incomplete config.")
    return

  _p(vs, f"Syncing {_b(name)}...")
  _p(vs, f"Connecting to {_b(host)}...")
  try:
    with ssh.session(host, None, password, identity) as session:
      _p(vs, "Connected.")
      push, pull, skip, err = _sync_pair(session, local_root, remote_root, vs, pattern)
      _p(vs, "")
      _p(vs, f"Done.  {_b('push')}:{_b(push)}  {_b('pull')}:{_b(pull)}  skip:{skip}  err:{err}")
  except OSError as e:
    _p(vs, f"{_b('SSH error')}: {e}")


def main(vs, args):
  cfg = _load_config()

  if len(args) < 2:
    _p(vs, "Usage:")
    _p(vs, "  sync remote [add|remove|list]")
    _p(vs, "  sync exec <name> [-f pattern]")
    return

  cmd = args[1]
  if cmd == "remote":
    _cmd_remote(vs, cfg, args[2:])
  elif cmd == "exec":
    if len(args) < 3:
      _p(vs, "Usage: sync exec <name> [-f pattern]")
      return
    pattern = None
    rest = args[3:]
    i = 0
    while i < len(rest):
      if rest[i] in ('--filter', '-f') and i + 1 < len(rest):
        pattern = rest[i + 1]
        i += 2
      else:
        i += 1
    _cmd_exec(vs, cfg, args[2], pattern)
  else:
    _p(vs, f"Unknown: {cmd}")
    _p(vs, "Usage: sync remote|exec")
