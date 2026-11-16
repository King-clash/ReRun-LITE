# ReRun LITE

ReRun LITE (version 1.2.0) is a small app for Grand Summoners on BlueStacks. It does one job, and does it with
a calm, good-looking window: **Auto Crest**. It farms a Crest Palace on Auto-Loop, scraps the crests you do not
want, and stops (and tells you on Discord) when a wanted one drops. A daily palace selector can pick which palace
to farm for you.

This is its own project, with its own version number (1.2.0), history, releases and update address. It is not a
fork of ReRun and nothing here changes or depends on the ReRun repository. (The code that does the farming was
copied from ReRun 1.2.1 when this repository was created; see "Where the code comes from".)

**Please read first:** Grand Summoners may not allow macros, bots or automation. Using ReRun LITE can lead to
account limits, suspension or a permanent ban. The warning is on the Auto Crest tab all the time.

## What is in it

| Tab | What it is |
|---|---|
| **Auto Crest** | Your emulators, Start / Dry Run / Pause / Stop, totals, crest counts (4+, Burst, Lv4, rate), instructions, Live View, and today's palace. |
| **History** | Crests kept and scrapped (with pictures), refills, sessions and problems. |
| **Templates** | Capture, test and import the pictures Crest looks for (for example your palace tile). |
| **Settings** | A side list in three groups. **Automation:** Auto Crest settings (per emulator, plus the daily schedule) and the Palace Selector. **Alerts:** Discord. **App:** General (tray, start options, setup check, updates, window, background) and the Log. |

Also included: the key sign-in, F12 (stop everything) and F11 (pause/resume), the tray icon, 24/7 mode, Dry Run,
Discord alerts with screenshots and the status board, the daily summary.

## Appearance

Settings > **Appearance** changes everything at once, with no restart. The choice is saved in `data/lite/ui.json`.

- **Look.** **Plain** (the default) is a quiet, flat design: tinted neutrals, hairline cards, one accent colour.
  **Classic** is ReRun's own black and white, unchanged. The other six bring their own colours and a looping
  background: **Ahri** (indigo night, blossom pink), **Midnight**, **Sakura** (light), **Ember**, **Aurora**, **Neon**.
- **Mode:** System (follows Windows), Light or Dark. It applies to Plain and Classic; a themed look has its own.
- **Accent colour:** Azure, Violet, Rose, Amber, Green, Teal, Coral, Slate, or any colour from the picker. It colours the
  main buttons, selection, toggles, focus and links, on any look. Text on it switches between white and dark so it
  always reads, and a too-pale or too-dark pick is nudged until it has enough contrast.
- **Contrast** (Standard, High) and **Density** (Comfortable, Compact: spacing about 12% tighter).
- **Background:** each themed look has its own video; Plain has none. Choose Off, any theme's video, or your own file.
- All colours come from one palette generated in OKLCH (`rerun_lite/colors.py`, `appearance.py`), so there are no
  colours scattered through the screens.

### Background video (themed looks)

- **A looping video plays behind the whole window** (the LITE themes only). It shows through the gaps between cards and
  behind the text; cards, buttons and the live view stay solid. Clicking the video does nothing, so nothing ever covers
  the window. It scales to any size, including maximised.
- **Buttons and text stay crisp.** Text and rounded buttons drawn straight onto a video come out ragged, so the video is
  softened in a patch behind every label and button, and the rounded corners are drawn without the dark dots the
  widget kit's own filter leaves. (Settings > Appearance > Background > *Behind buttons and text*: Off, Soft, Strong.)
- **Your own video (Ahri):** drop a file (mp4, webm, mkv, avi, mov or gif) into the `background` folder next to ReRun
  LITE and restart it. The first one in that folder plays. Or pick one for any theme in Settings > Appearance > Background.
- **Small videos are enlarged once.** A video under 1280 px wide (a GIF, say) is cleaned up (the GIF's dithering is
  smoothed), enlarged to 1080p with Lanczos resampling and lightly sharpened, in the background (a few seconds, all CPU
  cores), and kept in `data/lite/cache/`. The original plays until it is ready and is never changed. This makes a small
  video look cleaner; it cannot add detail that was never there, so a bigger source always looks better.
- Settings > General > **Background:** on/off, dimming (Light, Medium, Strong), behind buttons and text, smoothness
  (12, 20 or 30 frames a second), enlarge small videos, pause while Crest is running, and the video file. The video
  pauses by itself while the window is minimised.
- The five other themes' backgrounds, and Ahri's built-in one, are original animations drawn by
  `tools/make_background.py`. Ahri's default background is the "Star Guardian" GIF in `background/`; drop another video
  in there and the first one found plays instead.
- **The pictures stay attached to the app.** The exe carries a copy of the background videos, the 18 palace pictures
  (`images/`) and the palace list (`palaces.yaml`) inside itself, and on every start it puts back any that are missing
  from its folder (it never replaces a file that is there). So a new folder, a moved copy or a deleted file does not
  lose them. A personal build (`py build_lite.py`) also carries your palace schedule; the public release does not.
- **Whose they are:** the palace banners, the GIF and the game screenshots are other people's artwork, included so the
  app works out of the box. See [CREDITS.md](CREDITS.md); if you own one and want it removed, open an issue.

## Anime artwork

Settings > **Artwork** puts anime pictures in five places, for 16 anime. It is separate from the look: any anime's
artwork works on Plain, Classic or any themed look, and picking a character never changes the layout, the controls or
what Crest does. The choices are saved in `data/lite/ui.json`.

**ReRun LITE ships no anime artwork.** No AI pictures, no invented characters, no made-up posters, and nothing
downloaded from the web. The 16 collections (Jujutsu Kaisen, Solo Leveling, Naruto Akatsuki, Bleach, Evangelion, Demon
Slayer, One Piece, Attack on Titan, Chainsaw Man, Frieren, Cowboy Bebop, Tokyo Ghoul, Hunter x Hunter, Initial D,
Dragon Ball, Spy x Family) are ready, with their characters listed, but they have no pictures until you add your own:
Settings > Artwork > an anime > **Add picture...** next to a character, the background or the banner. Your pictures are
converted to WebP and kept on your PC in `data/lite/artwork/`. They are never uploaded, bundled or shared. The page
asks you once to only add pictures you own or may use.

- **Where it shows.** *Background:* a still picture behind the whole window (opacity 5-60%, blur 0-12, position
  centre/top/bottom/left/right). It replaces the look's video only while one is chosen, and never touches the Live View.
  *Header:* a banner under the Auto Crest title (height 40-140). *Instance:* a small portrait on each emulator row
  (off by default). *Panels:* a thin strip under the Totals tiles, beside the numbers, never under them. *Previews:* each
  anime's card in the gallery is a small picture of the real window drawn with that anime's art.
- **The library.** A gallery of the 16 anime with a search box (anime and character names), a Favourites filter, a
  character picker, alternate pictures per character, a favourite star, a reset for one anime or for everything, and one
  switch that turns all artwork off. Nothing on a screen with no picture changes at all: with nothing installed the
  window looks exactly as before.
- **It never interrupts Crest.** A change is drawn in place: the window is not rebuilt and the emulators and Crest are
  not touched, so it applies at once, even while Crest runs. Pictures are made ready on a worker thread; the same picture
  is never decoded twice (kept in memory, with a thumbnail on disk in `data/lite/cache/artwork/`); the background is
  blurred once on the CPU when you change it, not every frame; a missing or damaged picture just shows nothing.
- **For a bundled picture** (only for one whose licence allows it): put it under `assets/anime/<anime>/<backgrounds|
  characters|banners|previews>/` and record it with `py tools/artwork_tool.py add ...` (source address, licence, what
  use is permitted, attribution). A picture with no complete, approved entry in `assets/anime/manifest.json` is never
  shown. `py tools/artwork_tool.py check` lists any that would not be. Each anime's own settings (name, characters,
  accent colour, default opacity and blur) are in `assets/anime/<anime>/collection.json`, the same structure for all 16.

## Everyday conveniences

- **Start / Stop button** in the top bar, and **Ctrl+Enter** to start Crest on the selected emulator (or stop it
  when it is running). **Ctrl+.** stops everything.
- **Status chip** (top right): *Ready*, *Needs setup*, *Crest running on Instance 1*, *Paused* or *Error*. Click it to
  open Auto Crest (or, when something is missing, to go and fix it). The same words are added to the window title.
- **Tab badges:** a dot on Auto Crest while it runs, an orange ! on Auto Crest, Templates or Settings when something
  is missing.
- **"Needs setup" strip** on Auto Crest: says what would stop Crest from starting (no emulator, missing template
  pictures, no palace chosen) with a button that goes straight to the fix. Nothing is sent to the emulator to
  check this.
- **Today's palace** is shown under the warning on Auto Crest when the selector is on.
- **Command palette (Ctrl+K):** type a few letters and press Enter: go to a tab or a Settings page, start or stop
  Crest, change the look, mode, accent or density, copy a status summary.
- **Keyboard shortcuts you can change:** Settings > Keyboard shortcuts. Click a key, press the new combination (Esc
  cancels, Backspace removes it); a key already in use is refused. Defaults: Ctrl+1 to Ctrl+4 tabs, Ctrl+Tab /
  Ctrl+Shift+Tab step through them, Ctrl+, Settings, Ctrl+D dry run, Ctrl+Shift+C copy status, F1 lists them all.
- **Right-click menus** on emulators (start, dry run, pause, stop, copy address, edit, remove), the log, History and
  templates. Removing an emulator shows an **Undo** bar for a few seconds.
- **Templates:** a search box and a "Missing only" switch.
- **Pin on top** (Pin button, Ctrl+T, or Settings > General): keeps the window above the game while you watch.
- **Sound on alerts** (off by default): a short beep when Crest sends an alert.
- **Remembered:** window size and position, the open tab, the open Settings entry, the pin and the emulator you
  picked.
- **Settings > General > Window & files:** the on-top switch, sound, open the data folder, open the palace list and
  the shortcut list.

## Daily Crest Palace selector

Settings > Automation > **Palace Selector** chooses which Crest Palace Crest opens each day, using a picture of
that palace instead of one tile you captured by hand.

- **`palaces.yaml`** (next to ReRun LITE) is the one palace list: one palace per line, `Palace name: images/file.png`.
  Image paths are written only there. The pictures live in `images/`, each named after its palace.
- **Import from GS Companion** copies every palace banner from GS Companion's data folder (`crest_palace.json` and
  `images/stages/`) into `images/` as PNG, named after the palace, and adds the missing lines to the list. It never
  overwrites a picture that is already there or changes a line that is already in the list; it tells you what it
  left alone. The first import also fills the weekday table with a suggestion (the hardest palace open that day).
- **Mode:** *Weekday table* (a palace for each day of the week), *Cycle the list* (one palace per day in list order,
  wrapping; "Start with" says which one is today; "Only these" limits it), or *Off* (Crest uses its own palace
  settings as before).
- **The day** turns over at the game's reset, 6 AM UTC-6, not at your PC's midnight. The page shows today's palace
  and whether its picture is there.
- **Crest opens only today's palace.** The picture is looked for on the Crest Palace screen at any size (the
  GS Companion banners are not the game's own pixels). If the picture file is missing, nothing is chosen for today,
  or that palace is not on the screen (palaces rotate; the cycle does not know which days a palace is open), Crest
  stops and says which palace and which file. It never opens a different one.
- `palaces.yaml` and `images/` are game art and your own data, so they are not part of the repository.

## What is not in it

No other scripts (quests, arena, raids, mines, Login & Mail, Raid Tickets and so on), no checklist (the Dailies tab
was removed in 1.0.0), no custom routines, no Account Manager, no Units or Compendium, no GS Companion, and no
`/units` or `/compendium` Discord commands.

## Start it

You need Windows, Python 3.12 and BlueStacks. Install the libraries once with
`py -m pip install -r requirements.txt`.

- **From the source folder:** double-click `Run Rerun LITE.bat`, or run `py lite_main.py`.
- **As an exe:** `py build_lite.py` builds `dist/RerunLite/RerunLite.exe` (with the templates, the built-in
  background video and an empty `background` folder next to it). `py build_lite.py --release` builds a clean
  `release/RerunLite-<version>.zip` to share (blank config, its own Tesseract, nothing of yours; it is checked
  before it is zipped).

LITE asks for a sign-in key. The first time, **Settings > General > Setup check** shows what is missing. Crest
starts from the Home screen, so it needs either the palace selector, a picture of your palace tile (Templates
tab: `crest_palace_target`, or one per weekday) or the palace's name in **Auto Crest settings > Palaces to farm**.

If you also use the full ReRun, LITE can copy your settings, stats, crest log, History and key from its folder
the first time it starts (the ReRun folder is not changed). LITE keeps its own small files in `data/lite/`.

## Updates

LITE checks its own update address, `https://king-clash.github.io/ReRun-LITE/lite/`, for a signed manifest, and
compares it with LITE's own version (1.2.0). Until a LITE update has been published there, **Settings > General >
Check Now** says "No ReRun LITE updates have been published yet." A copy run from source only reports a new
version; the built exe also installs it. `py tools/publish_lite_update.py --exe release/RerunLite/RerunLite.exe`
writes the update site files (`updates_site/lite/`) for the `gh-pages` branch.

## Where the code comes from

The `rerun/` folder is a copy of the ReRun engine (version 1.2.1) that Crest runs on. `rerun_lite/` is what makes
it LITE:

- `manager.py` - `LiteManager`: the engine's `Manager` with the script list cut to Crest.
- `app.py` - `LiteApp`: start-up, the update, Discord and wording changes. It is built from mixins: `pages.py`
  (Auto Crest and Settings pages), `palace_page.py` (the Palace Selector page), `status.py` (status chip, badges,
  shortcuts, pin, the Window & files group), `extras.py` (Start/Stop button, sound, remembered emulator, today's
  palace), `palettes.py` (the themes as data), `background.py` (the video background and its settings), `upscale.py` (enlarging small videos) and `state.py` (window memory in
  `data/lite/ui.json`).
- `palaces.py` (the list, the day rule, the import) and `crest.py` (Crest with the selector).
- `readiness.py` - the local "is it ready?" checks behind the chip, badges and the setup strip.
- `theme.py` - the look (palette, outlined cards, the brand top bar, the grouped Settings list, tooltips), applied
  at run time so `rerun/` stays exactly as copied.
- `channel.py` - the update channel; `content.py` - the templates LITE ships; `bot.py`, `tray.py`, `icon.py` - the
  Discord bot, tray icon and icon.
- `lite_main.py` (entry point), `build_lite.py` and `build.py` (build), `tools/` (build log, update site, the
  background and how-to video makers), `tests/` (`py tests/test_lite.py`, `py tests/test_palaces.py`).

The copy of `rerun/` is not kept in step with ReRun automatically. A fix made there has to be brought over by hand.

## What has and has not been checked

- **Checked automatically:** the tests drive Auto Crest against a simulated game (scrap and redeploy, keep and
  stop, unknown crest, dry run), the palace selector (game-day clock, weekday and cycle choices, never opening
  another palace, the import never overwriting), the video background (it plays behind the window, follows it and
  switches off), the status and extras, the window, and the update channel against a local server. Every test passes.
- **Anime artwork:** the tests cover the 16 collections, that no picture is shown without a recorded right, adding,
  converting and removing your own pictures, the saved choices, search, the drawing, a still-picture background, and the
  window itself (every place the artwork appears, the Artwork page, a change leaving the window and Crest alone, any look,
  missing and damaged pictures) on Linux under a virtual display. **Not checked:** the background on Windows (it uses the
  same colour-key window as the video background, which cannot be tried on Linux) and how it looks with real artwork,
  because none is installed.
- **Not checked on the real game:** LITE as a whole has not been run against a live BlueStacks window. Crest itself
  is the script that was verified live in ReRun.
- **Not done:** no LITE update or release has been published yet. The exe is not code-signed, so Microsoft Defender
  may complain.
- **Sign-in and update signing use ReRun's key system.** The sign-in keys and the update signature come from the
  same key pair ReRun uses, so a key that works in ReRun works here.
- The exe still contains the engine's other code, but LITE has no way to start or show it. The download is about as
  large as ReRun's, because the big parts (image matching, the text reader) are what Crest needs.
