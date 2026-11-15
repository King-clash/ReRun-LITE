# Custom routines

Drop a `.yaml` file in this folder and it shows up in the Script list as
`Custom: <name>`. Files starting with `_` are helpers you can `call` but are
hidden from the list. Templates are the names you captured in the Templates tab.
Coordinates in `tap_xy` / `swipe` are for the 720x1280 portrait game frame.

| Step | Example | What it does |
|---|---|---|
| `tap` | `tap: ok_button` or `tap: {template: ok_button, timeout: 10, optional: true}` | Wait for a template, tap its centre |
| `tap_xy` | `tap_xy: [640, 360]` | Tap a fixed point |
| `wait` | `wait: {template: drop_info, timeout: 60}` | Wait until visible |
| `wait_gone` | `wait_gone: loading` | Wait until it disappears |
| `sleep` | `sleep: 2.5` | Pause |
| `back` | `back` | Android back key |
| `swipe` | `swipe: [640, 500, 640, 200, 400]` | Swipe x1 y1 x2 y2 ms |
| `if` | `if: {seen: popup, timeout: 3}` + `then:` / `else:` | Branch on what's on screen (`seen`, `not_seen`, `param`) |
| `loop` | `loop: {times: $runs, steps: [...]}` | Repeat (0 = forever) |
| `break` | `break` | Leave the innermost loop |
| `switch` | `switch: {timeout: 600, cases: [{template: win, steps: [...]}]}` | Wait for one of several screens |
| `tap_until` | `tap_until: {taps: [ok, next], until: home, timeout: 120}` | Tap through screens until one appears |
| `call` | `call: _helper` | Run another routine's steps |
| `notify` | `notify: {message: "Done", ping: true}` | Discord alert (+ screenshot) |
| `count` | `count: runs` | Add to this instance's stats |
| `stop` | `stop: out of stamina` | End the routine |
| `ensure_game` / `restart_game` | `ensure_game: {boot_wait: 20}` | Relaunch Grand Summoners if needed |

Top-level keys: `params` (values usable as `$name`), `interrupts` (templates
handled whenever they appear during waits), `recovery` + `max_recoveries`
(steps to run when a step times out).
