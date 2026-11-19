# ReRun LITE - draft notes for the next version (not published)

This is a draft. It covers the Crest Palace work done on 2026-11-19 only. The branch also holds the larger "run states,
sessions, analytics, compact mode, notifications, hotkeys, profiles, health page" work from commit 271d1e0, which is not
described here. Put both together under one version number before publishing. Nothing here has been released.

## New

- **Crest finds today's palace more reliably.** Before, if the palace picture did not match on the first look, Crest
  stopped. Now it tries, in this order, before it gives up:
  1. the palace picture;
  2. the palace's **name**, read from the screen (so a missing or out-of-date picture is no longer fatal, as long as the
     text reader is installed);
  3. a fresh look at the screen, twice (in case it was in the middle of an animation);
  4. **scrolling the list down** up to three pages. The list only shows four and a half palaces at a time, so the fifth
     (Temple of Heavenly Light, for example) used to be out of sight.
  If it finds the palace after scrolling, it taps it where it found it. If it never finds it, it scrolls the list back to the
  top and stops, and says so. It still never runs a different palace by guesswork.
- **It stops instead of tapping for ever.** If it taps a palace four times and the game never leaves the Crest Palace
  screen (a popup in the way, say), Crest stops and tells you.
- **It watches the daily limit.** The Temple of Heavenly Light's quest list says "Times playable x3, resets at 4:00 AM PST".
  Crest now logs how many plays are left and, at x0, stops with a clear message instead of starting a run the game will refuse.
- **Backup palaces, if you want them (off by default).** In Settings > Palace Selector you can turn on "Run a backup
  palace" and list palaces in order. Only when today's palace is nowhere on the Crest Palace screen does Crest try them. The Log
  and a Discord message say when one was used. With it off, Crest stops and runs no other palace, as before.
- **Two new buttons on the Palace Selector page.** *Check now* takes one screenshot of your emulator (nothing is tapped) and
  says which of your palaces are on the screen and whether today's is. *Add from screen…* cuts the picture of a palace that is
  not in your list out of that screenshot and adds it to `palaces.yaml` under the name you type, without ever replacing a
  picture or a line.
- **A picture is kept when it stops.** If Crest stops because the palace is not on the screen or a tile will not open, it saves
  the screen to the debug folder and puts the path in the message.
- **A tool that reads the game's own palace schedule:** `py tools/palace_schedule.py` opens Exploring > Schedule, reads the
  week, puts the filter buttons back as they were, and checks the selector's choice for each day. It found that **Shrine of
  Subspace** is on the Global schedule (Monday 11/23) but not in `palaces.yaml`; use *Add from screen…* when it is open.
- **"Read the game's schedule" button** (Settings > Palace Selector). It opens Exploring > Schedule in the game, reads about a
  week, puts the schedule's filter buttons back as it found them, closes the window, and tells you which day's chosen palace is
  not open that day. It asks first, will not run while Crest is running, and only taps menus.
- **Faster palace matching.** The palace pictures are now found about 2.6 times faster (a half-size pass, then a full-size look at
  the best few sizes), with the same answers on all 703 picture-and-screen pairs checked. A full check of 19 palaces went from about
  5 seconds to about 2.5.
- **Safer test and release checks.** `Run checks.bat` runs lint, every test and a trial build with its self-test, and says PASS or
  FAIL for each. The window tests no longer fail by chance: they retry when Windows briefly refuses to hand over a Tk file, and wait
  longer on a busy PC.
- **A second choice during four hours of the day.** The game's own schedule screen (Exploring > Schedule) starts each
  palace day at 0:00 PST, which is four hours before the 6 AM UTC-6 reset that ReRun uses. It is not yet known which clock
  the palaces really follow. For those four hours (08:00 to 12:00 UTC), if today's palace is nowhere on the list, Crest also
  looks for the palace the schedule gives for the next day, and writes that in the Log. At any other time it behaves as before.
- **A warning when the game has a palace you do not have.** If the Crest Palace screen shows a banner that matches none of
  the pictures in `palaces.yaml`, the Log says so once. It does not stop anything.
- **Shrine of Effulgence** (the limited palace that runs 11/17 to 11/30) was missing from the list. It is added, with a
  picture taken from the game.
- **A checker you can run yourself:** `py tools/template_health.py` compares the template pictures with screenshots and says
  which no longer match, and with `--live --palaces` it takes one screenshot of BlueStacks (nothing is tapped) and checks
  every palace picture against it. Run it after a game update.
- Small fixes: a stray unused import removed, and the "older versions" window no longer breaks if a key event arrives without
  its details.

## What has and has not been tested

- **Tested by computer:** all the automatic tests pass (even with the PC kept busy on purpose), including new ones for each step above (the picture, the name, the fresh look,
  scrolling, tapping where it was found, scrolling back when it gives up, the stuck-tap limit, the second choice only after
  today's palace is nowhere on the list, the new-palace warning, the plays-left reading from a real game screen, the backup
  palace, the schedule reader on real schedule screens, adding a palace safely, the two buttons, and the game's own pop-ups for
  "date has changed", maintenance and "please update").
- **Checked against the real game (version 4.1.2), without running Crest:** the pictures for the title screen, the Home
  screen's Exploring button, the Crest Palace entry and header, and the quest list all matched live screens (0.96 to 1.00).
  The palace pictures matched four of the five palaces that were open. Crest's search found a palace that is below the fold
  (Temple of Heavenly Light) by scrolling one page, and left the list where the tap would land on it. The built exe passes its
  own self-test.
- **Not tested on the real game:** the whole Crest loop (the Equip Crest screen and scrap or keep decisions), the name
  fallback on real screens in the middle of a run, and the four-hour second choice (it needs the game to be open in that
  window).
