# Crest Palaces: what was checked in the game

Everything here was read from the running game (Global, version 4.1.2) on 2026-11-19, not copied from a website. Run
`py tools/palace_schedule.py` to repeat it; it opens Exploring > Schedule, reads about a week, and puts the filter buttons back.

## The week (as listed by the game's own Schedule screen, 11/18 to 11/24)

| Game day | Palaces open |
|---|---|
| Monday | Shrine of Oblivion, Shrine of Perdition, **Shrine of Subspace** |
| Tuesday | Shrine of the Burning Chains, Shrine of Crimson Sea, Shrine of Cinderplume |
| Wednesday | Shrine of the Azul Knight, Shrine of Diamond Dust, Shrine of Frigidity |
| Thursday | Shrine of Aberration, Shrine of Eternity |
| Friday | Shrine of Adamantine, Shrine of Caliginosity |
| Saturday | Shrine of Whirlwind, Shrine of Cursed Claw |
| Sunday | Shrine of Discordia, Shrine of Tribulation, Shrine of Sagacity |
| Every day | Temple of Heavenly Light (on the Crest Palace screen; not a dated entry on the Schedule) |
| Limited | **Shrine of Effulgence**, 11/17 18:00 to 11/30 17:59 (every day in that span) |

Notes:
- **Subspace** is on the Global schedule (Monday 11/23). Older notes called it JP-only. It is not in `palaces.yaml` yet and has no
  picture; add it with Settings > Palace Selector > *Add from screen…* while it is on the Crest Palace screen.
- **Effulgence** is a limited-time palace and is in `palaces.yaml` (its picture was cut from the live screen).
- The Crest Palace screen shows about four and a half banners; the fifth (Temple of Heavenly Light) is below the fold. Crest scrolls
  the list to find it.
- A palace's quest list says "Open every <weekday>!" (Frigidity: Wednesday).

## Limits and clocks

- **Temple of Heavenly Light:** its quest list shows "Times playable x3" and "Resets at 4:00 AM PST". Crest logs the count and stops at x0.
- **The reset** (dailies, the Temple counter) is 4:00 AM PST = 12:00 UTC = 06:00 UTC-6, which is the game day LITE uses.
- **The Schedule screen** labels each palace slot 0:00 to 23:59 "PST" (08:00 UTC to 07:59 UTC). So from 08:00 to 12:00 UTC the schedule
  already shows the next day's palaces while LITE's game day is still the previous one. For those four hours Crest tries today's palace
  first (all the way down the list) and only then the schedule day's palace. Which clock the palaces really follow is still not
  confirmed by watching the game in that window.

## Suggested edits to the `rerun-crest-palace` skill (it lives in a plugin folder, so these are not applied)

1. Table: add **Shrine of Subspace** to Monday (remove it from the "JP-only, leave out" list), and add the **limited-time palace
   Shrine of Effulgence** (11/17 to 11/30 2026) as an every-day row that comes and goes.
2. Clock section: add that the Temple's own counter says "Resets at 4:00 AM PST", which matches the 06:00 UTC-6 game day, and that
   the Schedule screen starts palace days at 0:00 PST (the four-hour window above).
3. Images section: say there are now 19 pictures (Effulgence's came from the live screen at 632x130, not the GS Companion 580x150).
4. Add the safeguards in order (picture, name read from the screen, fresh look x2, scroll up to three pages, the second choice only in
   the four-hour window, the optional backup list, the stuck-tap limit of four, plays left).
5. "Keeping it current": last checked live 2026-11-19 with `tools/palace_schedule.py`.
