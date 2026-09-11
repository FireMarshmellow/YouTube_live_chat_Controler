from flask import Flask, request, render_template, redirect, url_for, jsonify
from pathlib import Path
import csv
import logging
import threading
import commandhandler
import patron_blinker
import tts_module
from storage import (
    load_commands,
    save_commands,
    load_secrets,
    save_secrets,
    load_plaques,
    save_plaques,
    update_plaque,
)
from youtube_utils import verify_youtube_keys

app = Flask(__name__)


class _HideRoutineRequests(logging.Filter):
    """Drop the web server's log line for every successful request; errors still show."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) == 3 and isinstance(args[1], str):  # '"GET /path HTTP/1.1" 200 -'
            code, request_line = args[1], str(args[0])
            return code[:1] not in ("1", "2", "3") and "/favicon.ico" not in request_line
        return True


logging.getLogger("werkzeug").addFilter(_HideRoutineRequests())

# Settings the app reads; shown on the Secrets page even before they are saved
KNOWN_SECRETS = [
    "TWITCH_OAUTH_TOKEN",
    "TWITCH_CHANNEL",
    "TWITCH_CLIENT_ID",
    "TWITCH_CLIENT_SECRET",
    "TWITCH_REFRESH_TOKEN",
    "api_key",
    "api_key_backup",
    "channel_id",
    "video_id",
    "access_token",
    "ha_url",
    "board_ip",
]

# Numeric board tuning values; edited on the Board Settings page, kept off the Secrets page
BOARD_SETTING_KEYS = {"segment_id", "num_slots", "hold_secs", "fade_steps", "step_delay", "chat_highlight_secs"}

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

@app.route('/secrets', methods=['GET', 'POST'])
def manage_secrets():
    secrets = load_secrets()
    if request.method == 'POST':
        for key, value in request.form.items():
            if key in BOARD_SETTING_KEYS:
                continue
            if key in KNOWN_SECRETS or key in secrets:
                secrets[key] = value.strip()
        save_secrets(secrets)
        return redirect(url_for('manage_secrets'))

    api_status = verify_youtube_keys(secrets)
    def categorize_secret(key: str) -> str:
        if key.startswith("TWITCH_"):
            return "Twitch"
        if key in {"api_key", "api_key_backup", "channel_id", "video_id"}:
            return "YouTube"
        if key in {"access_token", "ha_url"}:
            return "Home Assistant"
        if key == "board_ip":
            return "Hardware"
        return "Other"

    grouped_secrets = {}
    for key, value in {**dict.fromkeys(KNOWN_SECRETS, ""), **secrets}.items():
        if key in BOARD_SETTING_KEYS:
            continue
        grouped_secrets.setdefault(categorize_secret(key), []).append((key, value))

    category_order = ["Twitch", "YouTube", "Home Assistant", "Hardware", "Other"]

    return render_template(
        'manage_secrets.html',
        secrets=secrets,
        api_status=api_status,
        grouped_secrets=grouped_secrets,
        category_order=category_order,
    )

@app.route('/commands', methods=['GET', 'POST'])
def manage_commands():
    commands = load_commands()
    if request.method == 'POST':
        for command_name in commands.keys():
            commands[command_name]['enabled'] = f'enabled_{command_name}' in request.form
            commands[command_name]['timeout'] = int(request.form.get(f'timeout_{command_name}', commands[command_name]['timeout']))
            commands[command_name]['access_level'] = request.form.get(f'access_level_{command_name}', commands[command_name]['access_level'])
        save_commands(commands)
        return redirect(url_for('manage_commands'))

    def categorize(command_name: str) -> str:
        if command_name.startswith("!sound_"):
            return "Sounds"
        if command_name.startswith("!desk") or command_name in {"!bubbles", "!piston_up", "!piston_down"}:
            return "Home Assistant"
        return "Other"

    grouped = {}
    for name, details in commands.items():
        grouped.setdefault(categorize(name), []).append((name, details))

    # keep a stable order inside categories
    for entries in grouped.values():
        entries.sort(key=lambda item: item[0])

    category_order = ["Sounds", "Home Assistant", "Other"]

    return render_template(
        'manage_commands.html',
        grouped_commands=grouped,
        category_order=category_order,
        access_levels=get_access_levels()
    )


def load_led_layout():
    """Load the LED grid layout from CSV into a list of lists."""
    layout_path = Path("New_led_layout.csv")
    if not layout_path.exists():
        return []
    with layout_path.open("r", newline="") as f:
        reader = csv.reader(f)
        normalized_rows = []
        for row in reader:
            normalized_row = []
            for cell in row:
                val = int(cell)
                if val > 0:
                    normalized_row.append(val - 1)  # shift to 0-based indexing
                else:
                    # Use -1 as sentinel for "no LED" so ID 0 remains valid
                    normalized_row.append(-1)
            normalized_rows.append(normalized_row)
        return normalized_rows

# Function to get access levels
def get_access_levels():
    return {
        "regular": 1,
        "patreon": 2,
        "superchat": 3,
    }

@app.route('/test_commands', methods=['POST'])
def test_commands():
    command_input = request.form['command_input']
    commands = load_commands()
    if command_input in commands:
        commandhandler.execute_command(command_input, "Test User")
    else:
        print(f"Command '{command_input}' not recognized.")
    return redirect(url_for('manage_commands'))

@app.route('/update_command', methods=['POST'])
def update_command():
    command_name = request.form.get('command_name')
    enabled = request.form.get('enabled') == 'true'
    timeout = request.form.get('timeout')
    access_level = request.form.get('access_level')

    # Load the commands from the JSON file
    commands = load_commands()

    # Update the command with new values
    if command_name in commands:
        commands[command_name]['enabled'] = enabled
        commands[command_name]['timeout'] = int(timeout)
        commands[command_name]['access_level'] = access_level
        save_commands(commands)

        return jsonify({'message': f'Command {command_name} updated successfully.'}), 200
    else:
        return jsonify({'error': f'Command {command_name} not found.'}), 404

@app.route('/skip_tts', methods=['POST'])
def skip_tts():
    tts_module.skip_current_tts()  # Clear current audio and move to the next one
    return jsonify({"status": "success", "message": "Current TTS skipped!"})

@app.route('/pause_tts', methods=['POST'])
def pause_tts():
    paused = tts_module.toggle_pause()
    return jsonify({"status": "success", "paused": paused})

@app.route('/tts_status', methods=['GET'])
def tts_status():
    return jsonify({"paused": tts_module.is_paused()})



@app.route("/editor", methods=["GET", "POST"])
def editor():
    if request.method == "POST":
        yt_name = request.form["YT_Name"]
        leds_colour = request.form["Leds_colour"]
        leds = request.form["Leds"]
        update_plaque(yt_name, leds_colour, leds)
        return redirect(url_for("editor"))
    
    data = load_plaques()
    layout = load_led_layout()
    return render_template("patron_editor.html", data=data, led_layout=layout)

@app.route("/edit", methods=["POST"])
def edit():
    original_yt_name = request.form["original_YT_Name"]
    yt_name = request.form["YT_Name"]
    leds_colour = request.form["Leds_colour"]
    leds = request.form["Leds"]

    # Load and update data
    data = load_plaques()
    for entry in data:
        if entry["YT_Name"] == original_yt_name:
            entry["YT_Name"] = yt_name
            entry["Leds_colour"] = leds_colour
            entry["Leds"] = leds
            break
    save_plaques(data)

    return redirect(url_for("editor"))

@app.route("/delete", methods=["POST"])
def delete():
    yt_name = request.json.get("YT_Name")

    # Load data and filter out the entry with the given YT_Name
    data = load_plaques()
    data = [entry for entry in data if entry["YT_Name"] != yt_name]

    # Save the updated data back to the JSON file
    save_plaques(data)

    return jsonify({"status": "success"})

@app.route("/trigger_leds", methods=["POST"])
def trigger_leds():
    """Test a plaque from the editor using the same highlight chat messages get."""
    data = request.json or {}
    led_indices = patron_blinker.parse_leds(data.get('Leds', ''))
    color = data.get('Leds_colour', '#ffffff')
    if not led_indices:
        return jsonify({"status": "error", "message": "No LEDs specified"}), 400
    threading.Thread(target=patron_blinker.highlight_patron, args=(led_indices, color), daemon=True).start()
    return jsonify({"status": "success"})

@app.route('/animation/toggle', methods=['POST'])
def animation_toggle():
    return jsonify({"running": patron_blinker.toggle_animation()})

@app.route('/animation/status', methods=['GET'])
def animation_status():
    return jsonify({"running": patron_blinker.is_animation_running()})

@app.route('/board_settings', methods=['GET', 'POST'])
def board_settings():
    secrets = load_secrets()
    if request.method == 'POST':
        secrets['board_ip']   = request.form.get('board_ip', '').strip()
        secrets['segment_id'] = max(0, int(request.form.get('segment_id', patron_blinker.SEGMENT_ID)))
        secrets['num_slots']  = max(1, min(patron_blinker.MAX_SLOTS, int(request.form.get('num_slots', patron_blinker.NUM_SLOTS))))
        secrets['hold_secs']  = max(0.0, float(request.form.get('hold_secs', 0.0)))
        secrets['fade_steps'] = max(4, min(200, int(request.form.get('fade_steps', patron_blinker.FADE_STEPS))))
        secrets['step_delay'] = max(0.01, min(0.5, float(request.form.get('step_delay', patron_blinker.STEP_DELAY))))
        secrets['chat_highlight_secs'] = max(1.0, min(120.0, float(request.form.get('chat_highlight_secs', patron_blinker.CHAT_HIGHLIGHT_SECS))))
        save_secrets(secrets)
        return redirect(url_for('board_settings'))
    def number(key, default, cast):
        # Values may have been saved as text by older versions of the Secrets page
        try:
            return cast(float(secrets.get(key, default)))
        except (TypeError, ValueError):
            return default

    return render_template(
        'patron_settings.html',
        board_ip   = secrets.get('board_ip', ''),
        segment_id = number('segment_id', patron_blinker.SEGMENT_ID, int),
        num_slots  = number('num_slots', patron_blinker.NUM_SLOTS, int),
        hold_secs  = number('hold_secs', patron_blinker.HOLD_SECS, float),
        fade_steps = number('fade_steps', patron_blinker.FADE_STEPS, int),
        step_delay = number('step_delay', patron_blinker.STEP_DELAY, float),
        chat_highlight_secs = number('chat_highlight_secs', patron_blinker.CHAT_HIGHLIGHT_SECS, float),
        max_slots  = patron_blinker.MAX_SLOTS,
    )

# New plaque-related routes
@app.route('/plaques', methods=['GET'])
def get_plaques():
    return jsonify(load_plaques())

@app.route('/plaques', methods=['POST'])
def store_plaques():
    data = request.get_json()
    save_plaques(data)
    return jsonify({"status": "success"})

@app.route('/plaque-editor')
def plaque_editor():
    return render_template('plaques.html')

def run():
    secrets = load_secrets()
    patron_blinker.start_animation()
    app.run(host="0.0.0.0", port=8091, debug=False)

if __name__ == "__main__":
    secrets = load_secrets()
    patron_blinker.start_animation()
    app.run(host="0.0.0.0", port=8091, debug=False)
