# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

Patron Blinker is a standalone ambient LED animation system. It continuously picks random patrons from a list and pulses their assigned LEDs on a networked WLED board with a sinusoidal fade-in/fade-out effect (up to 5 patrons animating simultaneously). A Flask web UI lets you manage the patron list and board settings.

## Running

```bash
python patron_blinker.py
```

Flask serves on `0.0.0.0:8092`. No build step required. Requires `secrets.json` with `board_ip` set (configurable via the `/settings` page).

## File Structure

| File | Purpose |
|------|---------|
| [patron_blinker.py](patron_blinker.py) | Entry point: animation engine + Flask web UI |
| [storage.py](storage.py) | JSON read/write for `secrets.json` and `plaques.json` |
| [New_led_layout.csv](New_led_layout.csv) | 31×23 grid mapping positions to physical LED IDs (0–440) |
| [templates/patron_editor.html](templates/patron_editor.html) | LED grid editor — add/move/delete patrons |
| [templates/patron_settings.html](templates/patron_settings.html) | Board IP configuration form |

## Data Files (gitignored)

- **secrets.json** — only key used is `board_ip` (full URL, e.g. `http://192.168.1.100`)
- **plaques.json** — list of patron records: `YT_Name`, `Leds_colour` (hex), `Leds` (comma-separated 0-based LED indices)

## Architecture

`patron_blinker.py` spawns `NUM_SLOTS` (default 5) daemon threads on startup, each staggered by a random delay. Each thread loops forever: pick a random patron from `plaques.json` → call `animate_patron()` (sinusoidal brightness ramp via `sin(step/steps * π)`) → sleep a random idle interval → repeat. Secrets and plaques are reloaded from disk each cycle, so edits take effect without restart.

LED control sends HTTP POST to `{board_ip}/json/state` with a WLED-format `i`-array payload that sets only the specified LED indices, leaving all other LEDs untouched. This lets multiple slots animate different patrons concurrently without interference.

## Tuning Constants (top of patron_blinker.py)

| Constant | Default | Effect |
|----------|---------|--------|
| `NUM_SLOTS` | 5 | Max concurrent patron animations |
| `FADE_STEPS` | 40 | Smoothness of pulse (more = smoother) |
| `STEP_DELAY` | 0.06 s | Time per step → total pulse ≈ `STEPS × DELAY` |
| `MIN_IDLE` / `MAX_IDLE` | 2 / 8 s | Random gap between pulses per slot |
