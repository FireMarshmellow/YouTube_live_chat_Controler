from flask import Flask, request, render_template, redirect, url_for, jsonify
from pathlib import Path
import csv
from plaque_board_controller import set_leds
import commandhandler
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

@app.route('/', methods=['GET', 'POST'])
def index():
    return render_template('index.html')

@app.route('/secrets', methods=['GET', 'POST'])
def manage_secrets():
    secrets = load_secrets()
    if request.method == 'POST':
        secrets['TWITCH_OAUTH_TOKEN'] = request.form['TWITCH_OAUTH_TOKEN']
        secrets['TWITCH_CHANNEL'] = request.form['TWITCH_CHANNEL']
        secrets['api_key'] = request.form['api_key']
        secrets['api_key_backup'] = request.form['api_key_backup']
        secrets['channel_id'] = request.form['channel_id']
        secrets['video_id'] = request.form['video_id']
        secrets['access_token'] = request.form['access_token']
        secrets['ha_url'] = request.form['ha_url']
        secrets['board_ip'] = request.form['board_ip']
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
    for key, value in secrets.items():
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
        return [[int(cell) for cell in row] for row in reader]

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
    return render_template("editor.html", data=data, led_layout=layout)

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
    try:
        print("DEBUG: trigger_leds endpoint called")
        plaques = load_plaques()
        if plaques:
            print(f"DEBUG: Loaded {len(plaques)} plaques from file")
        else:
            print("DEBUG: No plaques file found")

        data = request.json
        yt_name = data.get('YT_Name')
        duration = data.get('time', 3)
        print(f"DEBUG: Searching for user: {yt_name}, duration: {duration}")
        
        matching_plaque = None
        for plaque in plaques:
            plaque_name = plaque.get('YT_Name')
            print(f"DEBUG: Checking plaque with YT_Name: {plaque_name}")
            if plaque_name and plaque_name.lower() == yt_name.lower():
                matching_plaque = plaque
                print("DEBUG: Found matching plaque!")
                break
        
        if matching_plaque:
            color = matching_plaque.get('Leds_colour', '#FFFFFF')
            color = color.lstrip('#')
            r, g, b = tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
            
            leds = matching_plaque.get('Leds', '')
            print(f"DEBUG: Attempting to trigger LEDs - Color: #{color}, Leds: {leds}")
            
            try:
                set_leds(leds, (r, g, b), duration)
                print("DEBUG: LED control successful")
                return jsonify({"status": "success"})
            except Exception as e:
                print(f"DEBUG: LED control error: {str(e)}")
                return jsonify({"status": "error", "message": f"LED control error: {str(e)}"}), 500
        else:
            print(f"DEBUG: No matching plaque found for user: {yt_name}")
            return jsonify({"status": "error", "message": f"No plaque found for user: {yt_name}"}), 404
            
    except Exception as e:
        print(f"DEBUG: Unexpected error in trigger_leds: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
    app.run(host="0.0.0.0", port=8091, debug=False)

if __name__ == "__main__":
    secrets = load_secrets()
    app.run(host="0.0.0.0", port=8091, debug=False)
