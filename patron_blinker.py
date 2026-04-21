import csv
import math
import random
import threading
import time
from pathlib import Path

import requests
from flask import Flask, jsonify, redirect, render_template, request, url_for

from storage import load_plaques, load_secrets, save_plaques, save_secrets

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

SEGMENT_ID = 1      # WLED segment index to target
NUM_SLOTS = 5       # default concurrent patron animations (overridden by secrets.json)
MAX_SLOTS = 10      # hard cap — threads spawned at startup
FADE_STEPS = 40     # brightness steps per half-fade (more = smoother)
STEP_DELAY = 0.06   # seconds per step → half-fade ≈ 2.4 s
MIN_IDLE = 2.0      # seconds between pulses (min)
MAX_IDLE = 8.0      # seconds between pulses (max)
MIN_SEND_INTERVAL = 0.05  # minimum seconds between HTTP sends

# ---------------------------------------------------------------------------
# Shared LED state — animation slots write here, render loop sends it
# ---------------------------------------------------------------------------

_led_state: dict = {}
_led_lock = threading.Lock()
_led_dirty = threading.Event()

_cached_endpoint = ""
_endpoint_refreshed_at = 0.0
_last_send = 0.0


def _get_endpoint() -> str:
    global _cached_endpoint, _endpoint_refreshed_at
    now = time.monotonic()
    if now - _endpoint_refreshed_at > 5.0:
        ip = load_secrets().get('board_ip', '').strip()
        _cached_endpoint = ip.rstrip('/') + "/json/state" if ip else ""
        _endpoint_refreshed_at = now
    return _cached_endpoint


def _write_leds(led_indices: list, hex_color: str) -> None:
    color = hex_color.lstrip('#')
    with _led_lock:
        for idx in led_indices:
            _led_state[idx] = color
    _led_dirty.set()


def _render_loop() -> None:
    """Single thread that owns all board communication."""
    global _last_send
    while True:
        changed = _led_dirty.wait(timeout=0.1)
        if not changed:
            continue
        _led_dirty.clear()
        endpoint = _get_endpoint()
        if not endpoint:
            continue
        gap = time.monotonic() - _last_send
        if gap < MIN_SEND_INTERVAL:
            time.sleep(MIN_SEND_INTERVAL - gap)
        # clear any writes that accumulated during the rate-limit sleep, then snapshot
        _led_dirty.clear()
        with _led_lock:
            snapshot = dict(_led_state)
        if not snapshot:
            continue
        try:
            payload: dict = {"tt": 0, "seg": {"id": SEGMENT_ID, "i": []}}
            for idx, color in snapshot.items():
                payload["seg"]["i"].extend([idx, color])
            requests.post(endpoint, json=payload, timeout=2)
            _last_send = time.monotonic()
        except Exception as exc:
            print(f"[render] {exc}")

# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------

def _scale_hex(hex_color: str, brightness: float) -> str:
    h = hex_color.lstrip('#')
    r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
    return f"{int(r * brightness):02x}{int(g * brightness):02x}{int(b * brightness):02x}"


def animate_patron(led_indices: list, hex_color: str, hold_secs: float = 0.0) -> None:
    half = FADE_STEPS // 2
    for step in range(half + 1):
        brightness = math.sin(step / FADE_STEPS * math.pi)
        _write_leds(led_indices, _scale_hex(hex_color, brightness))
        time.sleep(STEP_DELAY)
    if hold_secs > 0:
        time.sleep(hold_secs)
    for step in range(half, FADE_STEPS + 1):
        brightness = math.sin(step / FADE_STEPS * math.pi)
        _write_leds(led_indices, _scale_hex(hex_color, brightness))
        time.sleep(STEP_DELAY)
    _write_leds(led_indices, "000000")

# ---------------------------------------------------------------------------
# Animation engine — MAX_SLOTS independent daemon threads
# ---------------------------------------------------------------------------

_animation_active = threading.Event()
_animation_active.set()


def _animation_slot(slot_id: int) -> None:
    time.sleep(slot_id * random.uniform(0.8, 2.0))
    while True:
        if not _animation_active.is_set():
            time.sleep(1)
            continue
        secrets = load_secrets()
        active_slots = max(1, min(MAX_SLOTS, int(secrets.get('num_slots', NUM_SLOTS))))
        if slot_id >= active_slots:
            time.sleep(2)
            continue
        hold_secs = float(secrets.get('hold_secs', 0.0))
        try:
            pool = [p for p in load_plaques() if p.get('Leds') and p.get('Leds_colour')]
            if not pool:
                time.sleep(5)
                continue
            patron = random.choice(pool)
            led_indices = [int(x) for x in patron['Leds'].split(',') if x.strip()]
            if led_indices:
                animate_patron(led_indices, patron['Leds_colour'], hold_secs)
        except Exception as exc:
            print(f"[slot {slot_id}] {exc}")
            time.sleep(5)
        time.sleep(random.uniform(MIN_IDLE, MAX_IDLE))


def start_animation() -> None:
    threading.Thread(target=_render_loop, daemon=True).start()
    for i in range(MAX_SLOTS):
        threading.Thread(target=_animation_slot, args=(i,), daemon=True).start()

# ---------------------------------------------------------------------------
# Flask web UI
# ---------------------------------------------------------------------------

app = Flask(__name__)


def _load_led_layout() -> list:
    layout_path = Path("New_led_layout.csv")
    if not layout_path.exists():
        return []
    with layout_path.open("r", newline="") as f:
        return [
            [int(cell) - 1 if int(cell) > 0 else -1 for cell in row]
            for row in csv.reader(f)
        ]


@app.route('/')
def index():
    return render_template('patron_editor.html', data=load_plaques(), led_layout=_load_led_layout())


@app.route('/plaques', methods=['GET'])
def get_plaques():
    return jsonify(load_plaques())


@app.route('/plaques', methods=['POST'])
def store_plaques():
    save_plaques(request.get_json())
    return jsonify({"status": "success"})


@app.route('/delete', methods=['POST'])
def delete_patron():
    yt_name = request.json.get('YT_Name', '')
    save_plaques([p for p in load_plaques() if p.get('YT_Name') != yt_name])
    return jsonify({"status": "success"})


@app.route('/trigger_leds', methods=['POST'])
def trigger_leds():
    data = request.json
    led_indices = [int(x) for x in data.get('Leds', '').split(',') if x.strip()]
    color = data.get('Leds_colour', '#ffffff')
    if not led_indices:
        return jsonify({"status": "error", "message": "No LEDs specified"}), 400
    threading.Thread(target=animate_patron, args=(led_indices, color), daemon=True).start()
    return jsonify({"status": "success"})


@app.route('/animation/toggle', methods=['POST'])
def animation_toggle():
    if _animation_active.is_set():
        _animation_active.clear()
    else:
        _animation_active.set()
    return jsonify({"running": _animation_active.is_set()})


@app.route('/animation/status', methods=['GET'])
def animation_status():
    return jsonify({"running": _animation_active.is_set()})


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    secrets = load_secrets()
    if request.method == 'POST':
        secrets['board_ip'] = request.form.get('board_ip', '').strip()
        secrets['num_slots'] = max(1, min(MAX_SLOTS, int(request.form.get('num_slots', NUM_SLOTS))))
        secrets['hold_secs'] = max(0.0, float(request.form.get('hold_secs', 0.0)))
        save_secrets(secrets)
        return redirect(url_for('settings'))
    return render_template(
        'patron_settings.html',
        board_ip=secrets.get('board_ip', ''),
        num_slots=secrets.get('num_slots', NUM_SLOTS),
        hold_secs=secrets.get('hold_secs', 0.0),
        max_slots=MAX_SLOTS,
    )


if __name__ == '__main__':
    start_animation()
    app.run(host='0.0.0.0', port=8092, debug=False)
