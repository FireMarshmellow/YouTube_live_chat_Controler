import math
import random
import threading
import time

import requests

from storage import load_plaques, load_secrets

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

SEGMENT_ID       = 0     # WLED segment index — 0 = whole strip on a dedicated ESP32
NUM_SLOTS        = 7     # default concurrent patron animations (overridden by secrets.json)
MAX_SLOTS        = 10    # hard cap — threads spawned at startup
FADE_STEPS       = 60    # brightness steps per half-fade (more = smoother)
STEP_DELAY       = 0.05  # seconds per step → half-fade ≈ 3 s
HOLD_SECS        = 1.0   # seconds to hold peak brightness
MIN_IDLE         = 0.0   # seconds between pulses (min)
MAX_IDLE         = 0.5   # seconds between pulses (max)
CHAT_HIGHLIGHT_SECS = 10.0  # seconds a patron's plaque stays lit after they chat
HIGHLIGHT_FLASHES   = 3     # quick on/off flashes before the highlight holds
FLASH_DELAY         = 0.15  # seconds per flash on/off phase

# ---------------------------------------------------------------------------
# Board endpoint cache
# ---------------------------------------------------------------------------

_cached_endpoint    = ""
_endpoint_refreshed = 0.0


def _get_endpoint() -> str:
    global _cached_endpoint, _endpoint_refreshed
    now = time.monotonic()
    if now - _endpoint_refreshed > 5.0:
        ip = load_secrets().get('board_ip', '').strip()
        _cached_endpoint = ip.rstrip('/') + "/json/state" if ip else ""
        _endpoint_refreshed = now
    return _cached_endpoint

# ---------------------------------------------------------------------------
# LED conflict tracking — prevents two slots from touching the same LEDs
# ---------------------------------------------------------------------------

_claimed_leds: set = set()
_claim_lock        = threading.Lock()


def _try_claim(led_indices: list) -> bool:
    s = set(led_indices)
    with _claim_lock:
        if s & _claimed_leds:
            return False
        _claimed_leds.update(s)
        return True


def _release(led_indices: list) -> None:
    with _claim_lock:
        _claimed_leds.difference_update(led_indices)

# ---------------------------------------------------------------------------
# Chat highlights — LEDs here belong to the highlight, ambient writes skip them
# ---------------------------------------------------------------------------

_highlighted_leds: set = set()
_highlight_until: dict = {}   # { frozenset(led indices): monotonic deadline }
_highlight_epoch: dict = {}   # { led_idx: highlights started } — lets ambient pulses notice an interruption
_highlight_lock        = threading.Lock()


def _epochs(led_indices: list) -> list:
    return [_highlight_epoch.get(idx, 0) for idx in led_indices]

# ---------------------------------------------------------------------------
# Shared LED state — animation slots write here; render loop sends it
# ---------------------------------------------------------------------------

_led_state: dict = {}   # { led_idx: "rrggbb" }
_led_lock        = threading.Lock()
_led_dirty       = threading.Event()
_last_send       = 0.0
MIN_SEND_INTERVAL = 0.04  # seconds — ~25 sends/sec; must be < STEP_DELAY to avoid dropped frames


def _write_leds(led_indices: list, color: str, priority: bool = False) -> None:
    with _led_lock:
        for idx in led_indices:
            if priority or idx not in _highlighted_leds:
                _led_state[idx] = color
    _led_dirty.set()


def _render_loop() -> None:
    """Only thread that sends HTTP. Batches all active LED state into one request."""
    global _last_send
    while True:
        if not _led_dirty.wait(timeout=0.1):
            continue
        _led_dirty.clear()

        endpoint = _get_endpoint()
        if not endpoint:
            continue

        gap = MIN_SEND_INTERVAL - (time.monotonic() - _last_send)
        if gap > 0:
            time.sleep(gap)
        _led_dirty.clear()  # drain any writes that stacked up during sleep

        with _led_lock:
            snapshot = dict(_led_state)
        if not snapshot:
            continue

        i_arr = []
        for idx, color in snapshot.items():
            i_arr.extend([idx, color])
        seg_id = int(load_secrets().get('segment_id', SEGMENT_ID))
        try:
            requests.post(endpoint,
                          json={"v": False, "tt": 0, "seg": [{"id": seg_id, "i": i_arr}]},
                          timeout=2)
            _last_send = time.monotonic()
        except Exception as exc:
            print(f"[render] {exc}")

# ---------------------------------------------------------------------------
# Animation
# ---------------------------------------------------------------------------

def _scale_hex(hex_color: str, brightness: float) -> str:
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{int(r * brightness):02x}{int(g * brightness):02x}{int(b * brightness):02x}"


def parse_leds(leds: str) -> list:
    return [int(x) for x in (leds or '').split(',') if x.strip()]


def animate_patron(led_indices: list, hex_color: str, hold_secs: float = 0.0) -> None:
    if _highlighted_leds.intersection(led_indices):
        return  # patron is lit up by a chat highlight — leave them alone
    if not _try_claim(led_indices):
        return  # another slot already owns these LEDs — skip

    start_epochs = _epochs(led_indices)

    def interrupted() -> bool:
        # A chat highlight took over these LEDs; it handles the fade back to dark
        return _epochs(led_indices) != start_epochs

    try:
        secrets    = load_secrets()
        steps      = max(4, int(secrets.get('fade_steps', FADE_STEPS)))
        step_delay = max(0.01, float(secrets.get('step_delay', STEP_DELAY)))
        half       = steps // 2

        for step in range(half + 1):
            if interrupted():
                return
            _write_leds(led_indices, _scale_hex(hex_color, math.sin(step / steps * math.pi)))
            time.sleep(step_delay)

        if hold_secs > 0:
            time.sleep(hold_secs)

        for step in range(half, steps + 1):
            if interrupted():
                return
            _write_leds(led_indices, _scale_hex(hex_color, math.sin(step / steps * math.pi)))
            time.sleep(step_delay)

        if not interrupted():
            _write_leds(led_indices, "000000")
    finally:
        _release(led_indices)


def highlight_patron(led_indices: list, hex_color: str, hold_secs: float | None = None) -> None:
    """
    Flash a patron's LEDs, hold them at full brightness, then fade out.
    Overrides the ambient animation on those LEDs; a repeat call while lit
    extends the hold instead of starting a second highlight.
    """
    if not led_indices:
        return
    secrets = load_secrets()
    if hold_secs is None:
        hold_secs = max(1.0, float(secrets.get('chat_highlight_secs', CHAT_HIGHLIGHT_SECS)))
    key = frozenset(led_indices)

    with _highlight_lock:
        already_lit = key in _highlight_until
        if already_lit:
            _highlight_until[key] = max(_highlight_until[key], time.monotonic() + hold_secs)
            return
        # The hold starts once the opening flashes are done
        flash_secs = HIGHLIGHT_FLASHES * 2 * FLASH_DELAY
        _highlight_until[key] = time.monotonic() + flash_secs + hold_secs
        _highlighted_leds.update(key)
        for idx in key:
            _highlight_epoch[idx] = _highlight_epoch.get(idx, 0) + 1

    def time_left() -> float:
        with _highlight_lock:
            return _highlight_until[key] - time.monotonic()

    color = hex_color.lstrip('#').lower()
    steps = max(4, int(secrets.get('fade_steps', FADE_STEPS)))
    step_delay = max(0.01, float(secrets.get('step_delay', STEP_DELAY)))
    try:
        for _ in range(HIGHLIGHT_FLASHES):
            _write_leds(led_indices, color, priority=True)
            time.sleep(FLASH_DELAY)
            _write_leds(led_indices, "000000", priority=True)
            time.sleep(FLASH_DELAY)

        while True:
            _write_leds(led_indices, color, priority=True)
            while (remaining := time_left()) > 0:
                time.sleep(min(remaining, 0.2))

            # Fade out, but go back to holding if they chat again mid-fade
            for step in range(steps // 2, steps + 1):
                if time_left() > 0:
                    break
                _write_leds(led_indices, _scale_hex(color, math.sin(step / steps * math.pi)), priority=True)
                time.sleep(step_delay)
            else:
                break

        _write_leds(led_indices, "000000", priority=True)
    finally:
        with _highlight_lock:
            del _highlight_until[key]
            _highlighted_leds.difference_update(key)


def highlight_plaque(plaque: dict) -> None:
    """Run a chat highlight for a plaque record from plaques.json."""
    highlight_patron(parse_leds(plaque.get('Leds', '')), plaque.get('Leds_colour') or '#ffffff')

# ---------------------------------------------------------------------------
# Animation engine — MAX_SLOTS independent daemon threads
# ---------------------------------------------------------------------------

_animation_active = threading.Event()
_animation_active.set()
_started = False
_start_lock = threading.Lock()


def _animation_slot(slot_id: int) -> None:
    time.sleep(slot_id * random.uniform(0.8, 2.0))
    while True:
        if not _animation_active.is_set():
            time.sleep(1)
            continue
        secrets      = load_secrets()
        active_slots = max(1, min(MAX_SLOTS, int(secrets.get('num_slots', NUM_SLOTS))))
        if slot_id >= active_slots:
            time.sleep(2)
            continue
        hold_secs = float(secrets.get('hold_secs', HOLD_SECS))
        try:
            pool = [p for p in load_plaques() if p.get('Leds') and p.get('Leds_colour')]
            if not pool:
                time.sleep(5)
                continue
            patron      = random.choice(pool)
            led_indices = parse_leds(patron['Leds'])
            if led_indices:
                animate_patron(led_indices, patron['Leds_colour'], hold_secs)
        except Exception as exc:
            print(f"[slot {slot_id}] {exc}")
            time.sleep(5)
        time.sleep(random.uniform(MIN_IDLE, MAX_IDLE))


def start_animation() -> None:
    """Start the render loop and animation slots once per process."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_render_loop, daemon=True).start()
    for i in range(MAX_SLOTS):
        threading.Thread(target=_animation_slot, args=(i,), daemon=True).start()


def toggle_animation() -> bool:
    if _animation_active.is_set():
        _animation_active.clear()
    else:
        _animation_active.set()
    return _animation_active.is_set()


def is_animation_running() -> bool:
    return _animation_active.is_set()
