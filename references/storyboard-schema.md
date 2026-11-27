# Storyboard Schema Reference

A `demo-builder` storyboard is a JSON file describing the recording mode (`browser` or `terminal`), optional `ray.so`-style presentation framing, viewport or terminal appearance, synced zooms and highlights, multi-scene transitions and Picture-in-Picture (`pip`) overlays, narration, background music, captions, and ordered actions.

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
| `frame` | object \| string \| bool | `{"preset": "catppuccin"}` | `ray.so`-style gradient presentation frame (enabled by default; disable with `false`, `"none"`, or `--no-frame`) |
| `terminal` | object | `{}` | Terminal appearance, typing `cadence`, and shell settings (`terminal` mode; see below) |
| `narration` | object | `{}` | Narration defaults, step padding, and explicit cues (see below) |
| `music` | object | omitted | Optional instrumental background music track with automatic sidechain ducking (see below) |
| `captions` | object | `{}` | Caption wrapping and burn-in configuration (see below) |
| `steps` | list | required (single-scene) | Ordered list of actions for the chosen `mode` |
| `scenes` | list | omitted | Multi-scene array (replaces top-level `steps`; see below) |

## Presentation Frame (`frame`)

By default, `record_demo.py` composites the recording inside a `ray.so`-style diagonal gradient frame with rounded corners and a soft drop shadow. Pass `"frame": false`, `"frame": "none"`, or the CLI flag `--no-frame` to emit raw unframed video.

Shorthand string form: `"frame": "midnight"`. Object form:

| Field | Type | Default | Description |
|---|---|---|---|
| `preset` | string | `"catppuccin"` | Gradient preset: `"catppuccin"`, `"midnight"`, `"sunset"`, `"aurora"`, or `"none"` |
| `padding` | int | `48` | Outer gradient canvas padding in pixels on each side |
| `radius` | int | `16` | Corner radius in pixels for the foreground card |
| `shadow` | bool | `true` | Render a soft blurred drop shadow behind the foreground card |
| `window_bar` | bool | `false` | Prepend a 36 px macOS traffic-light window bar above the recording |
| `enabled` | bool | `true` | Toggle framing on or off |

## Browser actions (`mode: "browser"`)

Every action accepts an optional `after_ms` pause (milliseconds), an optional inline `narrate` cue, and optional `zoom` / `highlight` effects.

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

## Synced Zooms & Highlights (`step.zoom`, `step.highlight`)

Attach `zoom` and/or `highlight` directly to any browser or terminal step to draw the viewer's eye at the exact timestamp the step executes.

- **Target region:** in browser mode, supply `"selector"` (or omit it to inherit the step's `selector`) or explicit `"x"`, `"y"`, `"w"`, `"h"` pixel coordinates. In terminal mode, explicit `"x"`, `"y"`, `"w"`, `"h"` coordinates are required.

### `zoom` fields

| Field | Type | Default | Description |
|---|---|---|---|
| `selector` | string | `step.selector` | Browser CSS selector whose bounding box defines the zoom centre |
| `x`, `y`, `w`, `h` | float | omitted | Explicit pixel target region (required in `terminal` mode) |
| `scale` | float | `1.6` | Target zoom multiplier (`>= 1.0`) |
| `duration_ms` | float | `1500` | Total zoom window duration in milliseconds |
| `ease_ms` | int | `350` | Ease-in and ease-out ramp duration in milliseconds |

### `highlight` fields

| Field | Type | Default | Description |
|---|---|---|---|
| `selector` | string | `step.selector` | Browser CSS selector whose bounding box defines the highlighted region |
| `x`, `y`, `w`, `h` | float | omitted | Explicit pixel target region (required in `terminal` mode) |
| `style` | string | `"spotlight"` | `"spotlight"` (dims surround), `"callout"` (draws border), or `"both"` |
| `dim_opacity` | float | `0.45` | Surround dim opacity (`0.0–1.0`) for `"spotlight"` and `"both"` |
| `color` | string | `"#38bdf8"` | Border colour (hex or named ffmpeg colour) for `"callout"` and `"both"` |
| `border_width` | int | `3` | Border thickness in pixels |
| `duration_ms` | float | `1500` | Highlight visibility duration in milliseconds |

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
| `cadence` | string | omitted | Realistic typing cadence preset: `"smooth"`, `"brisk"`, `"human"`, or `"typewriter"` (see below) |
| `shell` | string | omitted | Shell binary (`Set Shell`, e.g. `"zsh"`, `"bash"`, `"nu"`) |
| `env` | object | omitted | Key/value environment variables emitted as `Env KEY "VALUE"` |
| `cwd` | string | omitted | Working directory entered inside a hidden `cd` preamble before recording |

### Terminal typing cadences (`cadence`)

Set `cadence` globally in `terminal.cadence` or override per step on any `"type"` action:

| Preset | Base speed | Behaviour |
|---|---|---|
| `"smooth"` | `35ms` | Crisp uniform typing with `90ms` breath pauses after shell operators (`&&`, `\|\|`, `\|`, `;`) |
| `"brisk"` | `22ms` | Fast, punchy typing for short demos |
| `"human"` | `45ms` | Deterministic per-token speed variation (`30–65ms`) plus micro-pauses after operators (`75ms`) and punctuation (`50ms`) |
| `"typewriter"` | `55ms` | Deliberate, slower cadence for emphasised commands |

## Terminal (`vhs`) actions

Every terminal action accepts an optional `after_ms` pause (emitted as `Sleep <ms>ms`), an optional inline `narrate` cue, and optional `zoom` / `highlight` effects (using `x`/`y`/`w`/`h`).

- `{"action": "type", "text": "uv run pytest -q", "speed": "35ms", "cadence": "human", "enter": true}` — types text (multi-line text splits on `\n` with `Enter`), optional per-step `speed`, `cadence`, and trailing `enter: true`
- `{"action": "enter", "count": 1}` — presses Enter `count` times
- `{"action": "pause", "ms": 1000}` (alias: `"sleep"`) — emits `Sleep <ms>ms`
- `{"action": "key", "key": "Tab", "count": 1}` — sends a named key (`Tab`, `Up`, `Down`, `Left`, `Right`, `Escape`/`esc`, `Backspace`, `Space`, `Delete`/`del`, `Enter`, `Home`, `End`, `PageUp`, `PageDown`)
- `{"action": "ctrl", "key": "l"}` — emits `Ctrl+<KEY>` (single-character keys are uppercased, e.g. `Ctrl+L`)
- `{"action": "hide"}` — pauses frame capture (`Hide`) for off-camera setup commands
- `{"action": "show"}` — resumes frame capture (`Show`)
- `{"action": "wait", "pattern": "\\$", "timeout": "10s"}` — waits for terminal output matching an optional regex `pattern` with an optional `timeout`

## Multi-Scene Storyboards (`scenes`, `transition`, `pip`)

Use a top-level `scenes` array instead of `steps` to stitch multiple browser and/or terminal scenes together with `ffmpeg` `xfade` transitions and optional Picture-in-Picture (`pip`) overlays. Each scene inherits top-level defaults (`mode`, `width`, `height`, `fps`, `color_scheme`, `cursor`, `terminal`, `narration`) and overrides only what changes. Narration and caption timestamps automatically shift to match the merged `xfade` timeline.

### Scene `transition`

Place `transition` on outgoing scenes (or incoming scenes) to control the `xfade` between adjacent scenes. String shorthand: `"transition": "smoothleft"`. Object form:

| Field | Type | Default | Description |
|---|---|---|---|
| `type` | string | `"fade"` | One of: `"fade"`, `"wipeleft"`, `"wiperight"`, `"slideleft"`, `"slideright"`, `"smoothleft"`, `"smoothright"`, `"dissolve"`, `"zoomin"` |
| `duration` | float | `0.5` | Transition overlap duration in seconds (alternatively specify `duration_ms` in milliseconds) |

### Scene `pip` overlay

Add a `pip` object to any scene to record a secondary stream (e.g. a live terminal alongside a browser view) and composite it as a rounded corner card:

| Field | Type | Default | Description |
|---|---|---|---|
| `mode`, `steps`, `terminal` | scene fields | inherited | Sub-scene recording definition rendered into the PiP card |
| `corner` | string | `"bottom-right"` | `"bottom-right"`, `"bottom-left"`, `"top-right"`, or `"top-left"` |
| `scale` | float | `0.32` | PiP card width as a fraction of the base canvas width (`0.0 < scale <= 1.0`) |
| `margin` | int | `28` | Inset margin in pixels from the chosen corner |
| `start` | float | `0.0` | Start timestamp (seconds within the scene) when PiP appears |
| `end` | float \| null | `null` | Optional end timestamp (seconds within the scene) when PiP hides |
| `radius` | int | `12` | Corner radius in pixels for the PiP card |
| `border_color` | string | `"#cdd6f4"` | PiP border colour (hex or named ffmpeg colour) |
| `border_width` | int | `2` | PiP border width in pixels |

## Narration (`narration` and `step.narrate`)

Narration cues are extracted from inline `step.narrate` fields (single-scene or per-scene) and top-level `narration.cues`, hashed by `(model, voice, speed, text)` with SHA-256, and resolved from `--narration-dir` (default `<out-dir>/.narration-cache`).

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

## Background Music (`music`)

Add a top-level `music` object to plan and cache an instrumental bed via `--plan-media` (`fal.ai` OAuth MCP). When narration is present, `record_demo.py` automatically loops/trims the track to match video duration, applies fade-in/fade-out, and ducks the music beneath speech using `ffmpeg`'s `sidechaincompress` filter.

| Field | Type | Default | Description |
|---|---|---|---|
| `prompt` | string | required | Instrumental music generation prompt (avoid vocals when paired with narration) |
| `model` | string | `"fal-ai/cassetteai/music-generator"` | `fal.ai` music generation model ID |
| `duration_sec` | float | `30` | Requested generation duration in seconds |
| `volume` | float | `0.18` | Base music gain multiplier (`>= 0`) |
| `duck_db` | float | `-12.0` | Sidechain ducking attenuation in dB during speech (`<= 0`) |
| `fade_in` | float | `1.0` | Fade-in duration in seconds |
| `fade_out` | float | `1.5` | Fade-out duration in seconds |

## Captions (`captions`)

Whenever a storyboard produces narration cues, `record_demo.py` automatically writes synced `<name>.vtt` (WebVTT) and `<name>.srt` (SubRip) sidecar files into `--out-dir`.

| Field | Type | Default | Description |
|---|---|---|---|
| `burn_in` | bool | `false` | Burn captions into the MP4/WebM via `ffmpeg`'s `subtitles` filter (also enabled by `--burn-captions`) |
| `max_chars` | int \| null | `48` | Maximum characters per wrapped caption line (`null` disables wrapping) |

## Working Examples

### Terminal storyboard (`vhs` with typing cadence)

```json
{
  "name": "cli-quickstart",
  "mode": "terminal",
  "poster_time": 2.0,
  "frame": {
    "preset": "catppuccin",
    "padding": 48,
    "radius": 16,
    "shadow": true
  },
  "terminal": {
    "width": 1280,
    "height": 720,
    "fps": 30,
    "theme": "Catppuccin Mocha",
    "font_size": 18,
    "padding": 24,
    "window_bar": "Colorful",
    "cadence": "smooth",
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
    {"action": "type", "text": "uv run pytest -q", "cadence": "human", "enter": true, "after_ms": 1200},
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
    "font_size": 18,
    "cadence": "smooth"
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

### Studio-polished multi-scene storyboard (frame, zoom, highlight, PiP, transitions, ducked music)

```json
{
  "name": "launch-showcase",
  "width": 1280,
  "height": 720,
  "fps": 30,
  "poster_time": 8.5,
  "frame": {
    "preset": "midnight",
    "padding": 48,
    "radius": 16,
    "shadow": true,
    "window_bar": true
  },
  "narration": {
    "model": "fal-ai/kokoro/american-english",
    "voice": "af_heart",
    "speed": 1.02,
    "pad_steps": true,
    "gap_ms": 300
  },
  "music": {
    "prompt": "warm minimal lo-fi synth pad, subtle pulse, 96 bpm, clean product demo, no vocals",
    "model": "fal-ai/cassetteai/music-generator",
    "duration_sec": 30,
    "volume": 0.18,
    "duck_db": -12.0,
    "fade_in": 1.0,
    "fade_out": 1.5
  },
  "captions": {
    "burn_in": false,
    "max_chars": 48
  },
  "scenes": [
    {
      "mode": "terminal",
      "terminal": {
        "theme": "Catppuccin Mocha",
        "font_size": 18,
        "window_bar": null,
        "cadence": "human"
      },
      "transition": {
        "type": "smoothleft",
        "duration": 0.5
      },
      "steps": [
        {"action": "pause", "ms": 400},
        {
          "action": "type",
          "text": "deploy --prod",
          "enter": true,
          "after_ms": 900,
          "narrate": "Ship to production with a single command.",
          "highlight": {
            "x": 40,
            "y": 40,
            "w": 420,
            "h": 60,
            "style": "callout",
            "color": "#38bdf8",
            "duration_ms": 1400
          }
        }
      ]
    },
    {
      "mode": "browser",
      "pip": {
        "mode": "terminal",
        "corner": "bottom-right",
        "scale": 0.32,
        "margin": 28,
        "start": 0.5,
        "radius": 12,
        "border_color": "#cdd6f4",
        "border_width": 2,
        "terminal": {
          "theme": "Catppuccin Mocha",
          "window_bar": null,
          "cadence": "brisk"
        },
        "steps": [
          {"action": "type", "text": "tail -f deploy.log", "enter": true, "after_ms": 1500}
        ]
      },
      "steps": [
        {"action": "goto", "url": "http://127.0.0.1:8765/dashboard.html", "wait_until": "networkidle"},
        {
          "action": "click",
          "selector": "#status-badge",
          "after_ms": 1200,
          "narrate": "The dashboard updates live while logs stream in the corner.",
          "zoom": {
            "selector": "#status-badge",
            "scale": 1.5,
            "duration_ms": 1800,
            "ease_ms": 350
          },
          "highlight": {
            "selector": "#status-badge",
            "style": "spotlight",
            "dim_opacity": 0.45,
            "duration_ms": 1800
          }
        }
      ]
    }
  ]
}
```

## Tips for great product demos

- Keep clips focused on one hero flow (**8–18 seconds** for silent loops, **15–30 seconds** for narrated walkthroughs).
- Start with a `500–800 ms` establishing shot before moving the cursor or typing.
- Use `drag` with `steps: 30` for silky-smooth 3D camera orbits.
- Avoid enabling both `frame.window_bar: true` and `terminal.window_bar: "Colorful"` in the same scene so you do not get double title bars.
- Keep `crf` around `22–24` for sharp UI and terminal text under 3–4 MB per clip.
