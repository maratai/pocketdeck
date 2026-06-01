importScripts('https://cdn.jsdelivr.net/pyodide/v0.26.2/full/pyodide.js');

let pyodide = null;
let ready = false;
let running = false;

const STUB_FILES = [
  '_runner.py', 'vscreen.py', 'pdeck.py', 'esclib.py', 'anm.py',
  'dsplib.py', 'xbmreader.py', 'pdeck_utils.py', 'overlay.py', 'audio.py',
  'ujson.py', 'network.py', 'termios.py', 'machine.py', 'micropython.py',
  // Japanese input (PEM): socket bridges HTTP to sync-XHR for henkan; fontloader
  // is a no-op since the browser renders CJK glyphs itself.
  'socket.py', 'fontloader.py'
];

// ── Bundled demo apps ────────────────────────────────────────────────────────
const BUILTIN_APPS = {

  // ── Real Pocket Deck apps, imported from the served lib/ tree ──────────────
  'pem': {
    label: 'PEM Editor',
    desc: 'PEM is emacs-style editor',
    // Open the demo welcome.md on launch (resolved against /sd/Documents cwd).
    code: `import pem
def main(vs, args):
  pem.main(vs, ['pem', 'welcome.md'])
`
  },

  'home': {
    label: 'Home',
    desc: 'The home app. Function is limited, it won\'t launch apps. Just for demo.',
    code: `import home
def main(vs, args):
  home.main(vs, args)
`
  },

};

// ── Worker machinery ─────────────────────────────────────────────────────────

async function loadStubs() {
  for (const name of STUB_FILES) {
    const resp = await fetch(`./stubs/${name}`);
    if (!resp.ok) throw new Error(`Cannot load stub: ${name}`);
    pyodide.FS.writeFile(`/home/pyodide/${name}`, await resp.text());
  }
}

self.onmessage = async (e) => {
  const msg = e.data;

  // ── init ─────────────────────────────────────────────────────────────────
  if (msg.type === 'init') {
    try {
      // SharedArrayBuffer layout (created by main thread):
      //   meta   : Int32Array  at byte 0  — [0]=head [1]=tail [2]=stop
      //   data   : Uint8Array  at byte 64 — keystroke byte ring
      //   kstate : Uint8Array  after ring — HID-keycode -> 0/1 state table
      const sab = msg.sab;
      const RING = 2048, KSTATE = 256;
      self.emulator_meta   = new Int32Array(sab, 0, 16);
      self.emulator_data   = new Uint8Array(sab, 64, RING);
      self.emulator_kstate = new Uint8Array(sab, 64 + RING, KSTATE);

      // Allow Python (send_char) to inject keys into the same ring.
      self.emulator_push_key = (str) => {
        const meta = self.emulator_meta, data = self.emulator_data;
        const bytes = new TextEncoder().encode(str);
        let head = Atomics.load(meta, 0);
        for (const b of bytes) { data[head % RING] = b; head++; }
        Atomics.store(meta, 0, head);
        Atomics.notify(meta, 0);
      };

      self.emulator_post_raw = (jsonStr) => {
        try { self.postMessage(JSON.parse(jsonStr)); }
        catch (_) { self.postMessage({ type: 'error', message: jsonStr }); }
      };

      // Clipboard: a worker-side buffer shared across apps (persists between runs).
      // Copy also mirrors to the system clipboard on the main thread.
      self.emulator_clipboard = '';
      self.emulator_clip_set = (s) => {
        self.emulator_clipboard = String(s);
        self.postMessage({ type: 'clipboard_copy', data: String(s) });
      };
      self.emulator_clip_get = () => self.emulator_clipboard;

      // Synchronous fetch so Python's (synchronous) import machinery can pull
      // modules from the served /lib tree on demand. Workers allow sync XHR.
      self.emulator_fetch_text = (url) => {
        try {
          const xhr = new XMLHttpRequest();
          xhr.open('GET', url, false);
          xhr.send();
          return xhr.status === 200 ? xhr.responseText : null;
        } catch (_) { return null; }
      };

      pyodide = await loadPyodide({
        indexURL: 'https://cdn.jsdelivr.net/pyodide/v0.26.2/full/',
      });

      await pyodide.runPythonAsync(`
import sys
if '/home/pyodide' not in sys.path:
    sys.path.insert(0, '/home/pyodide')
`);

      await loadStubs();

      // Drop any stdlib 'socket' Pyodide pre-imported so our /home/pyodide stub
      // (loaded above) is the one jp_input picks up on first import.
      await pyodide.runPythonAsync(`
import sys
for _m in ('socket', 'fontloader'):
    sys.modules.pop(_m, None)
`);

      // Seed the device-like filesystem so apps that read /config and /sd work.
      try {
        for (const d of ['/config', '/config/ssh', '/sd', '/sd/Documents', '/sd/work', '/sd/py', '/sd/lib', '/sd/Documents/pd'])
          try { pyodide.FS.mkdirTree(d); } catch (_) {}
        const apps = [
          ["Pem",          { type:"program", command:[["pem"]],          description:"Pem text editor" }],
          ["Analog Clock", { type:"program", command:[["analog_clock"]], description:"Clock, calendar and timer" }],
          ["Nudoc",        { type:"program", command:[["nudoc"]],        description:"Sudoku game" }],
          ["Invader",      { type:"program", command:[["invader"]],      description:"Space invaders" }],
          ["Music",        { type:"program", command:[["music"]],        description:"Music player" }],
        ];
        pyodide.FS.writeFile('/config/apps.json', JSON.stringify(apps));
        pyodide.FS.writeFile('/config/settings.json', '{}');

        // Load the demo documents (sd_template/Documents) into /sd/Documents so
        // PEM and other apps open into a folder with real content.
        const manifest = self.emulator_fetch_text('../sd_template/Documents/_manifest.json');
        if (manifest) {
          for (const name of JSON.parse(manifest)) {
            const body = self.emulator_fetch_text('../sd_template/Documents/' + name);
            if (body != null) pyodide.FS.writeFile('/sd/Documents/' + name, body);
          }
        }
        // Loads PEM manual
        const body = self.emulator_fetch_text('../docs/pem_readme.md');
        pyodide.FS.writeFile('/sd/Documents/pd/pem_readme.md', body);
      } catch (e) { /* non-fatal */ }

      // Install an import hook: any module not satisfied by the built-in stubs
      // is fetched from the served Pocket Deck /lib tree (lib/ and lib/examples/).
      // Appended to meta_path so our emulator stubs in /home/pyodide win first.
      await pyodide.runPythonAsync(`
import sys, importlib.abc, importlib.util
from js import emulator_fetch_text

_LIB_DIRS = ['../lib/', '../lib/examples/']
_src_cache = {}

def _fetch_lib(name):
    if name in _src_cache:
        return _src_cache[name]
    for d in _LIB_DIRS:
        src = emulator_fetch_text(d + name + '.py')
        if src is not None:
            _src_cache[name] = (src, d + name + '.py')
            return _src_cache[name]
    _src_cache[name] = None
    return None

class _LibFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, name, path, target=None):
        if '.' in name:
            return None
        if _fetch_lib(name) is None:
            return None
        return importlib.util.spec_from_loader(name, self)
    def create_module(self, spec):
        return None
    def exec_module(self, module):
        src, fname = _fetch_lib(module.__name__)
        exec(compile(src, fname, 'exec'), module.__dict__)

if not any(isinstance(f, _LibFinder) for f in sys.meta_path):
    sys.meta_path.append(_LibFinder())
`);

      ready = true;
      self.postMessage({
        type: 'ready',
        apps: Object.entries(BUILTIN_APPS).map(([id, a]) => ({
          id, label: a.label, desc: a.desc
        }))
      });
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) });
    }
    return;
  }

  if (!ready) {
    self.postMessage({ type: 'error', message: 'Worker not initialised yet' });
    return;
  }

  // ── run ──────────────────────────────────────────────────────────────────
  if (msg.type === 'run') {
    if (running) {
      self.postMessage({ type: 'error', message: 'An app is already running — stop it first' });
      return;
    }
    const appEntry = BUILTIN_APPS[msg.app];
    const code = (appEntry && appEntry.code) || '';
    if (!code) {
      self.postMessage({ type: 'error', message: 'Unknown app: ' + msg.app });
      return;
    }
    const args = JSON.stringify(msg.args || [msg.app || 'app']);
    pyodide.FS.writeFile('/home/pyodide/_userapp.py', code);

    // Clear the stop flag and drain any stale input before starting.
    Atomics.store(self.emulator_meta, 2, 0);                 // stop = 0
    Atomics.store(self.emulator_meta, 1, Atomics.load(self.emulator_meta, 0)); // tail = head

    running = true;
    try {
      // run_app blocks this worker thread (Atomics.wait) until the app exits.
      await pyodide.runPythonAsync(`
import sys
for _m in ['vscreen', 'pdeck', '_runner', 'overlay', 'anm', 'pdeck_utils']:
    sys.modules.pop(_m, None)
from _runner import run_app
run_app('/home/pyodide/_userapp.py', ${args})
`);
    } catch (err) {
      self.postMessage({ type: 'error', message: String(err) });
    } finally {
      running = false;
    }
    return;
  }

  // Note: while an app is running this worker is blocked in Atomics.wait,
  // so 'key' / 'stop' are delivered via the SharedArrayBuffer from the main
  // thread, not through these message handlers.
};
