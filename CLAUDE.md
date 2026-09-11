# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

A stream companion app. It reads YouTube live chat (gRPC `liveChatMessages.streamList`) and Twitch chat, reads messages aloud with TTS, runs chat commands (sounds, Home Assistant), and drives a WLED "patron board": an ambient animation pulses random supporters' plaques, and when a supporter chats their plaque flashes and stays lit. A Flask web UI manages settings, commands and the plaque layout.

## Running

Double-click `run.bat` (creates `.venv` with Python 3.10–3.13 on first run, reinstalls when `requirements.txt` changes, starts `main.py`, opens `http://127.0.0.1:5000`).

`python app.py` runs only the web UI + board animation on port 8091, without chat or TTS.

## File Structure

| File | Purpose |
|------|---------|
| [main.py](main.py) | Entry point: YouTube/Twitch chat listeners, `handle_message` routing, starts board animation + Flask |
| [app.py](app.py) | Flask routes: secrets, commands, plaque editor, board settings, TTS and animation controls |
| [patron_blinker.py](patron_blinker.py) | LED engine: render loop, ambient animation slots, chat highlights |
| [storage.py](storage.py) | JSON read/write for `secrets.json`, `commands.json`, `plaques.json` (per-file lock + temp-file replace); `find_plaque` name matching |
| [tts_module.py](tts_module.py) | Single audio queue: TTS (SAPI via pyttsx3, DECtalk via `say.exe` called without a shell) and sound effects play one at a time in chat order |
| [currency.py](currency.py) | Super Chat amounts converted to £ with free daily rates (open.er-api.com), cached; falls back to YouTube's own amount string |
| [commandhandler.py](commandhandler.py) | Chat command permissions (supporter = `find_plaque` match), cooldowns and actions; Home Assistant/desk actions run on background threads |
| [stream_list.proto](stream_list.proto) | Google's streamList proto (with a missing import added); `stream_list_pb2*.py` are generated from it |
| [New_led_layout.csv](New_led_layout.csv) | 31×23 grid mapping positions to physical LED IDs (1-based in file, 0-based after loading) |

## Data Files (gitignored)

- **secrets.json** — API keys, `channel_id`/`video_id`, Home Assistant, `board_ip` (full URL), board tuning (`segment_id`, `num_slots`, `hold_secs`, `fade_steps`, `step_delay`, `chat_highlight_secs`)
- **plaques.json** — patron records: `name`, `YT_Name`, `twitchusername`, `Leds_colour` (hex), `Leds` (comma-separated 0-based LED indices), editor `pos`/`plaqueType`
- **commands.json** — command settings, auto-synced with `sounds/*.mp3`

## Patron Board Architecture

`_render_loop` is the only thread that sends HTTP: it batches `_led_state` into one WLED `{board_ip}/json/state` POST with a segment `i`-array.

Ambient: `MAX_SLOTS` threads each pick a random plaque and run `animate_patron` (sine fade in → hold → fade out). `_try_claim` stops two slots animating the same LEDs.

Chat highlight: `handle_message` → `find_plaque` → `highlight_plaque` → `highlight_patron` (flashes, holds for `chat_highlight_secs`, fades). While a highlight runs its LEDs are in `_highlighted_leds`; ambient writes to them are dropped, and an ambient pulse that sees `_highlight_epoch` change aborts. Repeat chats extend the hold. The editor's Test button uses the same highlight.

`find_plaque` compares names with `@`, case, spaces, `.`, `_`, `-` ignored: `YT_Name` first, then `twitchusername`, then plaque `name`.

Secrets and plaques are re-read from disk while running, so edits take effect without a restart.
