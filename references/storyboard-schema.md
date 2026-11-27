# Storyboard Schema Reference

A `demo-builder` storyboard is a JSON file describing the recording mode (`browser` or `terminal`), viewport or terminal appearance, optional narration and captions, and ordered actions.

## Top-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | filename stem | Output stem for `<name>.mp4`, `<name>.webm`, `<name>.png`, `<name>.vtt`, `<name>.srt` |
| `mode` | `"browser"` \| `"terminal"` | `"browser"` | Recording backend: Playwright Chromium (`browser`) or Charmbracelet `vhs` (`terminal`) |
| `width` | int | `1280` | Viewport or terminal width in pixels |
| `height` | int | `720` | Viewport or terminal height in pixels |
| `fps` | int | `30` | Output video framerate |
| `color_scheme` | `"dark"` \| `"light"` | `"dark"` | Browser `prefers-color-scheme` (`browser` mode) |
| `cursor` | bool | `true` | Inject animated glowing cursor + click ripples (`browser` mode) |
| `poster_time` | float | `1.5` | Timestamp (seconds) for poster PNG capture |
| `terminal` | object | `{}` | Terminal appearance and shell settings (`terminal` mode; see below) |
| `narration` | object | `{}` | Narration defaults, step padding, and explicit cues (see below) |
| `captions` | object | `{}` | Caption wrapping and burn-in configuration (see below) |
| `steps` | list | required | Ordered list of actions for the chosen `mode` |

## Browser actions (`mode: "browser"`)

Every action accepts an optional `after_ms` pause (milliseconds) and an optional inline `narrate` cue.

- `{"action": "goto", "url": "http://127.0.0.1:8765/app.html", "wait_until": "networkidle"}`
- `{"action": "wait_for", "selector": "#canvas", "state": "visible", "timeout": 10000}`
- `{"action": "pause", "ms": 1200}`
- `{"action": "move", "selector": "#btn", "steps": 18}` (or `"x"`, `"y"`)
- `{"action": "hover", "selector": "#card", "steps": 18}`
- `{"action": "click", "selector": "#tab-map", "steps": 16, "pre_ms": 120}` (or `"x"`, `"y"`)
- `{"action": "dblclick", "selector": "#node"}`
- `{"action": "drag", "selector": "#stage", "dx": 180, "dy": -60, "steps": 30}` (or `from_x/from_y/to_x/to_y`)
- `{"action": "type", "selector": "input", "text": "Seren Voss", "delay": 55}`
- `{"action": "press", "key": "Enter"}`
- `{"action": "scroll", "selector": "#panel", "dx": 0, "dy": 320}`
- `{"action": "eval", "script": "window.scrollTo(0, 0)"}`

## Terminal settings (`mode: "terminal"`)

Configure under the top-level `terminal` object (CLI flags `--width`, `--height`, and `--fps` override storyboard values):

| Field | Type | Default | Description |
|---|---|---|---|
| `width` | int | `1280` | Terminal canvas width in pixels |
| `height` | int | `720` | Terminal canvas height in pixels |
| `fps` | int | `30` | Output framerate (`Set Framerate`) |
| `theme` | string \| object | `"Catppuccin Mocha"` | Built-in `vhs` theme name or custom theme JSON object |
| `font_family` | string | omitted | Custom terminal font family (`Set FontFamily`) |
| `font_size` | int | `16` | Font size in pixels (`Set FontSize`) |
| `padding` | int | `24` | Inner terminal padding in pixels (`Set Padding`) |
| `window_bar` | string \| null | `"Colorful"` | Window chrome style (`"Colorful"`, `"Rings"`, etc.; `null` omits `Set WindowBar`) |
| `typing_speed` | string \| int | `"45ms"` | Default per-character delay (VHS duration string or integer milliseconds) |
| `shell` | string | omitted | Shell binary (`Set Shell`, e.g. `"zsh"`, `"bash"`, `"nu"`) |
| `env` | object | omitted | Key/value environment variables emitted as `Env KEY "VALUE"` |
| `cwd` | string | omitted | Working directory entered inside a hidden `cd` preamble before recording |

## Terminal (`vhs`) actions

Every terminal action accepts an optional `after_ms` pause (emitted as `Sleep <ms>ms`) and an optional inline `narrate` cue.

- `{"action": "type", "text": "uv run pytest -q", "speed": "35ms", "enter": true}` — types text (multi-line text splits on `\n` with `Enter`), optional per-step `speed` and trailing `enter: true`
- `{"action": "enter", "count": 1}` — presses Enter `count` times
- `{"action": "pause", "ms": 1000}` (alias: `"sleep"`) — emits `Sleep <ms>ms`
- `{"action": "key", "key": "Tab", "count": 1}` — sends a named key (`Tab`, `Up`, `Down`, `Left`, `Right`, `Escape`/`esc`, `Backspace`, `Space`, `Delete`/`del`, `Enter`, `Home`, `End`, `PageUp`, `PageDown`)
- `{"action": "ctrl", "key": "l"}` — emits `Ctrl+<KEY>` (single-character keys are uppercased, e.g. `Ctrl+L`)
- `{"action": "hide"}` — pauses frame capture (`Hide`) for off-camera setup commands
- `{"action": "show"}` — resumes frame capture (`Show`)
- `{"action": "wait", "pattern": "\\$", "timeout": "10s"}` — waits for terminal output matching an optional regex `pattern` with an optional `timeout`

## Narration (`narration` and `step.narrate`)

Narration cues are extracted from both inline `step.narrate` fields and top-level `narration.cues`, hashed by `(model, voice, speed, text)` with SHA-256, and resolved from `--narration-dir` (default `<out-dir>/.narration-cache`).

### Top-level `narration` fields

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | string | `"fal-ai/kokoro/american-english"` | Default `fal.ai` TTS model ID |
| `voice` | string | `"af_heart"` | Default voice preset |
| `speed` | float | `1.0` | Default speaking rate multiplier |
| `pad_steps` | bool | `true` | Automatically pad narrated steps so each stays on screen for at least `clip_duration + gap_ms` |
| `gap_ms` | int | `250` | Extra breathing room (milliseconds) appended after padded steps |
| `volume` | float | `1.0` | Audio gain multiplier passed to `ffmpeg` |
| `cues` | list | `[]` | Explicit timeline cues: `{"text": "...", "at": 0.5, "model": "...", "voice": "...", "speed": 1.0}` |

### Inline `step.narrate`

Attach narration directly to any browser or terminal step so its start time tracks the step automatically:

- **String shorthand:** `"narrate": "Run the test suite with a single command."`
- **Object form (with per-cue overrides):**
  `{"text": "All checks pass in under a second.", "voice": "af_bella", "speed": 1.05, "at": 4.2}`

## Captions (`captions`)

Whenever a storyboard produces narration cues, `record_demo.py` automatically writes synced `<name>.vtt` (WebVTT) and `<name>.srt` (SubRip) sidecar files into `--out-dir`.

| Field | Type | Default | Description |
|---|---|---|---|
| `burn_in` | bool | `false` | Burn captions into the MP4/WebM via `ffmpeg`'s `subtitles` filter (also enabled by `--burn-captions`) |
| `max_chars` | int \| null | `48` | Maximum characters per wrapped caption line (`null` disables wrapping) |

## Working Examples

### Terminal storyboard (`vhs`)

```json
{
  "name": "cli-quickstart",
  "mode": "terminal",
  "poster_time": 2.0,
  "terminal": {
    "width": 1280,
    "height": 720,
    "fps": 30,
    "theme": "Catppuccin Mocha",
    "font_size": 18,
    "padding": 24,
    "window_bar": "Colorful",
    "typing_speed": "40ms",
    "shell": "zsh",
    "env": {
      "NO_COLOR": "0"
    }
  },
  "steps": [
    {"action": "hide"},
    {"action": "type", "text": "export PS1='$ '", "enter": true},
    {"action": "ctrl", "key": "l"},
    {"action": "show"},
    {"action": "pause", "ms": 500},
    {"action": "type", "text": "uv run pytest -q", "enter": true, "after_ms": 1200},
    {"action": "wait", "pattern": "passed", "timeout": "10s"},
    {"action": "pause", "ms": 1000}
  ]
}
```

### Narrated storyboard with captions

```json
{
  "name": "cli-narrated",
  "mode": "terminal",
  "poster_time": 2.5,
  "terminal": {
    "width": 1280,
    "height": 720,
    "theme": "Catppuccin Mocha",
    "font_size": 18
  },
  "narration": {
    "model": "fal-ai/kokoro/american-english",
    "voice": "af_heart",
    "speed": 1.0,
    "pad_steps": true,
    "gap_ms": 250,
    "cues": [
      {"at": 0.2, "text": "Let's verify the project in one deterministic command."}
    ]
  },
  "captions": {
    "burn_in": false,
    "max_chars": 48
  },
  "steps": [
    {
      "action": "type",
      "text": "make verify",
      "enter": true,
      "after_ms": 800,
      "narrate": "Make verify runs ruff formatting, linting, and the full pytest suite."
    },
    {
      "action": "pause",
      "ms": 1200,
      "narrate": {
        "text": "Every check is green and ready for review.",
        "speed": 1.05
      }
    }
  ]
}
```

## Tips for great product demos

- Keep clips focused on one hero flow (**8–16 seconds**).
- Start with a `600–900 ms` establishing shot before moving the cursor or typing.
- Use `drag` with `steps: 30` for silky-smooth 3D camera orbits.
- Keep `crf` around `22–24` for sharp UI and terminal text under 3–4 MB per clip.
