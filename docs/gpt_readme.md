
# gpt

`gpt` is a ChatGPT frontend for Pocket Deck. It supports text queries, voice
input/output, file and image attachments, and an **agent mode** in which the
model uses native function calling (tools) to write files, run and debug code,
and even see and drive other apps on the device. An optional **conversation
mode** keeps context across turns.

Requires an OpenAI API key stored at `/config/openai_api_key`.

> The previous markdown-code-block agent (the older `gpt`) is still shipped as
> `gpt_l` ("legacy") if you need it. The library plumbing it provides
> (`chatgpt_util`, STT/TTS, logging) also lives in `gpt_l`.

## Basic Usage

```
gpt [options] [question]
```

With no question argument, an interactive prompt opens for multi-line input
(single-shot). In conversation mode (`-C`) a prompt opens that keeps talking to
you turn after turn.

**Quick examples:**

```
gpt what is the capital of France
gpt -f notes.txt notes2.txt -q summarize this
gpt -v
gpt -a write a temp script that prints the first 10 primes and run it
gpt -C -r coder          # interactive coding session with tools on
```

## Options

Option | Description
-------|------------
`-q text or file` | Explicit question. If a single filename is given, its content is used as the question.
`content` | Positional question text (alternative to `-q`).
`-a` | Agent mode — turn on the function-calling tools. See [Agent Mode](#agent-mode-a).
`-C` | Conversation mode — keep context across turns. See [Conversation Mode](#conversation-mode-c).
`-P` | Start in Plan mode (confirm each `command_with_return` / `write_file` before it runs). Default is Auto.
`-r name|text` | Role / persona. Presets: `assistant` (default) or `coder` (also turns tools on). Or a `/sd/roles/<name>.txt` file, or literal role text.
`-f file [file...]` | Attach one or more files as reference context. Also accepts URLs.
`-i img [img...]` | Attach image files or URLs for vision queries.
`-c` | Use clipboard content as reference text.
`-m model` | Model to use. Shortcuts: `f`/`fast` → gpt-5.4-mini, `m`/`medium` → ngpt-5.4, `h`/`high` → gpt-5.5. Default: `gpt-5.4`.
`-e level` | Reasoning effort: `low`, `medium` (default), or `high`.
`-j` | Answer in Japanese. Also switches terminal font to Unicode automatically.
`-v` | Voice mode: record audio → STT → ask GPT → TTS reads answer aloud.
`-vt type` | TTS voice type. Options: `alloy`, `coral` (default), `echo`, `fable`, `onyx`, `nova`, `shimmer`.
`-n` | Do not save the response log.
`-nf` | No formatting (skip bold/markdown rendering).
`-s` | Silent mode — suppress progress indicators.
`--log-file file` | Internal: reuse a specific log filename across turns/iterations.

## Voice Mode (`-v`)

Voice mode combines STT and TTS into a single conversational interaction:

1. Records audio from the microphone (press any key to stop).
2. Transcribes audio via OpenAI Whisper (STT).
3. Sends transcription to GPT, optimized for spoken response.
4. Reads the response aloud via OpenAI TTS.

```
gpt -v
gpt -v -vt nova
```

Voice mode uses the `tts-1-hd` model with WAV output, streamed directly to the
audio engine.

## Inline Directives

Inside your message, you can embed `[[options]]` blocks to override options
per-message without re-typing flags on the command line.

```
[[options]]
```

Supported inline options:

Option | Effect
-------|-------
`-m model` | Override the model for this message.
`-e level` | Set reasoning effort (`low`/`medium`/`high`).
`-j` | Answer in Japanese.
`-c` | Include clipboard as reference.
`-nf` | Disable formatting.
`-n` | Do not save the log.
`-v` | Enable voice output.
`-vt type` | Set TTS voice type.
`-i img [img...]` | Attach image file(s) or URL(s).

`-f` is **not** accepted inside `[[...]]`; use a bare file reference instead (see
below).

## Prompt file syntax

You can give a file as a prompt, `gpt -q prompt.md`. It is useful with agent
mode `-a`. In the file you can use the following syntax:

### File reference

You can use an Obsidian-style file link to attach a file as reference context.

```markdown
[[note.md]]
Analyze note.md.
```

You can also set options inline with `[[...]]`:

```markdown
[[pd/app_development.md]]
[[-m gpt-5.5]]
[[-e high]]
[[/sd/py/hello.py]]

Modify hello.py so it prints hello in multiple languages, then run it.
```

To run such a prompt in agent mode:

```
gpt -a -q prompt.md
```

## Log Files

Responses are saved to `/sd/log/` by default (created automatically). The log
filename is copied to the clipboard after each session. Use `-n` to skip saving.

## Agent Mode (`-a`)

Agent mode gives the model a set of **function tools** it calls directly (native
function calling over the Responses API) instead of emitting special markdown
blocks. The core loop is write → run → read output → fix → re-run.

`/sd/Documents/pd/README.md` and `/sd/Documents/pd/gpt_output_rules.md` are
attached automatically so the model knows the Pocket Deck basics.

When the model invokes a tool you'll see a `[Call]` line and a `[Result]` line.
The `coder` role (`-r coder`) also turns agent mode on automatically.

### Tools

Tool | What it does
-----|-------------
`command_with_return` | Run a module/command (e.g. `ls`, `cat`, `grep`, or any app's `main(vs, args)`) and return its captured output. Prefix with `r ` to force a fresh reload of a module you just edited.
`write_file` | Create or overwrite a file. The previous version is backed up under `/sd/backup/` automatically.
`launch_app` | Launch a Pocket Deck app by name, optionally with arguments (e.g. a file to open).
`list_running_apps` | List which app is on which screen.
`switch_screen` | Bring a screen to the foreground (0-based in the tool; the GUI shows 1-based).
`capture_screen` | Take a screenshot of a screen and feed it back to the model as an image.
`send_keys` | Type text / keystrokes into the foreground app (supports escape sequences for arrows, Esc, Backspace, Ctrl-X, etc.).

### write_file output

When `write_file` runs, the full file content is **not** dumped to the screen.
Instead:

- **Updating an existing file** — a diff (via the `diff` command) is shown, so
  you see exactly what changed. The original is backed up to `/sd/backup/`.
- **Creating a new file** — the content is printed once under a `[New file]`
  header (there is nothing to diff against).

### Auto vs Plan mode

Two execution modes control the effectful tools (`command_with_return` and
`write_file`):

- **Auto** (default) — tools run without asking.
- **Plan** (`-P`, or toggle at runtime) — each `command_with_return` /
  `write_file` is shown and you confirm it first. Press Enter / `y` to run, `n`
  to skip, or type a reason to decline (the reason is sent back to the model as
  feedback). Other tools (screen/app inspection) always run.

In conversation mode, **Shift-Tab** toggles Auto/Plan, or use `/mode`,
`/auto`, `/plan`.

## Conversation Mode (`-C`)

`gpt -C` opens an interactive session that keeps context across turns
(server-side, via `previous_response_id`), so you can have a back-and-forth
without re-sending history. Combine with `-a`/`-r coder` for an interactive
coding assistant.

Line editing: arrows move the cursor, Up/Down browse history, Ctrl-A/E jump to
start/end, Ctrl-K/U kill to end/start, Ctrl-C cancels the current line.

**Japanese input:** Alt+` or Alt+j toggles a kana (romaji → kana → kanji) IME.
Use `-j` so the Unicode terminal font is loaded first.

### Slash commands

Command | Effect
--------|-------
`/help` | Show command help.
`/quit`, `/exit` | Leave the conversation.
`/clear`, `/reset` | Start fresh (clear the server-side context).
`/model [name]` | Show or set the model (`m`/`medium`, `h`/`high`, `f`/`fast`, or an id).
`/effort [level]` | Show or set reasoning effort (`low`/`medium`/`high`).
`/role [name\|text]` | Show or set the role (`assistant` or `coder`; resets context).
`/tools` | Toggle the function-calling tools on/off.
`/mode [auto\|plan]` | Show/set execution mode (no arg toggles); also `/auto`, `/plan`.
`/file <path>` | Attach a file as reference for the next message.
`/history` | Show recent input history.

## Roles (`-r`)

A role sets the assistant's persona / system prompt.

- `assistant` (default) — a plain, concise helper.
- `coder` (aliases `coding`, `code`) — an expert MicroPython coding assistant
  for Pocket Deck; **this preset turns the tools on**.
- A path or a name under `/sd/roles/<name>.txt` — your own role text from a file.
- Any other text is used verbatim as the role.
