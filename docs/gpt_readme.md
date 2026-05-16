
# gpt

`gpt` is a ChatGPT frontend for Pocket Deck. It supports text queries, voice input/output, file and image attachments, and an autonomous agent mode that can write and execute code on the device.

Requires an OpenAI API key stored at `/config/openai_api_key`.

## Basic Usage

```
gpt [options] [question]
```

With no question argument, an interactive prompt opens for multi-line input.

**Quick examples:**

```
gpt what is the capital of France
gpt -f notes.txt notes2.txt -q summarize this
gpt -v
gpt -a -q prompt.md
```

## Options

Option | Description
-------|------------
`-q text or file` | Explicit question. If a single filename is given, its content is used as the question.
`content` | Positional question text (alternative to `-q`).
`-f file [file...]` | Attach one or more files as reference context. Also accepts URLs.
`-i img [img...]` | Attach image files or URLs for vision queries.
`-c` | Use clipboard content as reference text.
`-m model` | Model to use. Shortcuts: `f`/`fast` → gpt-5.4-mini, `m`/`medium` → ngpt-5.4, `h`/`high` → gpt-5.5. Default: `gpt-5.4`.
`-j` | Answer in Japanese. Also switches terminal font to Unicode automatically.
`-v` | Voice mode: record audio → STT → ask GPT → TTS reads answer aloud.
`-vt type` | TTS voice type. Options: `alloy`, `coral` (default), `echo`, `fable`, `onyx`, `nova`, `shimmer`.
`-n` | Do not save the response log.
`-nf` | No formatting (skip bold/markdown rendering).
`-s` | Silent mode — suppress progress indicators.
`-a` | Agent mode. See [Agent Mode](#agent-mode) below.
`--log-file file` | Internal: reuse a specific log filename across agent iterations.

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

Voice mode uses the `tts-1-hd` model with WAV output, streamed directly to the audio engine.

## Inline Directives

Inside your message, you can embed `[[options]]` blocks to override options per-message without re-typing flags on the command line.

```
[[options]]
```

Supported inline options:

Option | Effect
-------|-------
`-m model` | Override the model for this message.
`-j` | Answer in Japanese.
`-c` | Include clipboard as reference.
`-nf` | Disable formatting.
`-n` | Do not save the log.
`-v` | Enable voice output.
`-vt type` | Set TTS voice type.


## Prompt file file syntax

You can give a file as a prompt, `gpt -q prompt.md`. It is useful with agent mode `-a`.
In the file, you can use the following syntax:

### File reference

You can use Obsidian style file link to add file reference.
```markdown
[[note.md]]
Analyze note.md.
```

Next example is for agent coding. AI understand how to code by giving app_development.md.
You can also change options if you specify option in `[[]]`.

```markdown
[[pd/app_development.md]]
[[-m gpt-5.5]]
[[/sd/py/hello.py]]

Modify hello.py and save it. Print hello in multiple languages.
```
To run the prompt in agent mode:
```
gpt -a -q prompt.md
```


## Log Files

Responses are saved to `/sd/log/` by default (created automatically). The log filename is copied to the clipboard after each session. Use `-n` to skip saving.

## Agent Mode (`-a`)

Agent mode lets GPT write files and execute code autonomously on the device. GPT's response is parsed for special code blocks that trigger actions.

`/sd/Documents/pd/README.md` are loaded automatically, so AI knows about Pocket Deck in Agent mode.

Agent mode also backs up any existing file before overwriting it to `/sd/backup/`.
