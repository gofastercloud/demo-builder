# Storyboard Schema Reference

A `product-demo` storyboard is a JSON file describing the viewport, theme, and ordered browser actions.

## Top-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | filename stem | Output stem for `<name>.mp4`, `<name>.webm`, `<name>.png` |
| `width` | int | `1280` | Viewport and video width in pixels |
| `height` | int | `720` | Viewport and video height in pixels |
| `color_scheme` | `"dark"` \| `"light"` | `"dark"` | Browser `prefers-color-scheme` |
| `cursor` | bool | `true` | Inject animated glowing cursor + click ripples |
| `poster_time` | float | `1.5` | Timestamp (seconds) for poster PNG capture |
| `steps` | list | required | Ordered list of actions |

## Action types

Every action accepts an optional `after_ms` pause (milliseconds).

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

## Tips for great product demos

- Keep clips focused on one hero flow (**8–16 seconds**).
- Start with a `600–900 ms` establishing shot before moving the cursor.
- Use `drag` with `steps: 30` for silky-smooth 3D camera orbits.
- Keep `crf` around `22–24` for sharp UI text under 3–4 MB per clip.
