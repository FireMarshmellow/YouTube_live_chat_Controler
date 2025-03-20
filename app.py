from flask import Flask, request, render_template, redirect, url_for, jsonify, send_from_directory
import json
import os
from plaque_board_controller import set_leds
import commandhandler
import tts_module

app = Flask(__name__)

SECRETS_FILE = 'secrets.json'
COMMANDS_FILE = 'commands.json'
PLAQUES_FILE = 'plaques.json'

def load_commands():
    with open(COMMANDS_FILE, 'r') as file:
        return json.load(file)

# Save commands to JSON file
def save_commands(commands):
    with open(COMMANDS_FILE, 'w') as file:
        json.dump(commands, file, indent=4)

# Function to load data from JSON
def load_secrets():
    if not os.path.exists(SECRETS_FILE):
        return []  # Return empty list if file does not exist
    with open(SECRETS_FILE, "r") as file:
        return json.load(file)

# Save secrets to JSON file
def save_secrets(secrets):
    with open(SECRETS_FILE, 'w') as file:
        json.dump(secrets, file, indent=4)

# Function to load data from JSON
def load_data():
    if not os.path.exists(PLAQUES_FILE):
        return []  # Return empty list if file does not exist
    with open(PLAQUES_FILE, "r") as file:
        return json.load(file)

# Function to save data to JSON
def save_data(data):
    with open(PLAQUES_FILE, "w") as file:
        json.dump(data, file, indent=4)

# Function to update data in JSON
def update_data(yt_name, leds_colour, leds):
    data = load_data()
    
    # Check if the entry already exists (based on YT_Name)
    for entry in data:
        if entry["YT_Name"] == yt_name:
            entry["Leds_colour"] = leds_colour
            entry["Leds"] = leds
            break
    else:
        # If no match is found, add a new entry
        data.append({
            "YT_Name": yt_name,
            "Leds_colour": leds_colour,
            "Leds": leds
        })
    
    save_data(data)

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

    return render_template('manage_secrets.html', secrets=secrets)

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

    return render_template('manage_commands.html', commands=commands, access_levels=get_access_levels())

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



@app.route("/editor", methods=["GET", "POST"])
def editor():
    if request.method == "POST":
        yt_name = request.form["YT_Name"]
        leds_colour = request.form["Leds_colour"]
        leds = request.form["Leds"]
        update_data(yt_name, leds_colour, leds)
        return redirect(url_for("editor"))
    
    # Load data for display
    data = load_data()
    return render_template("editor.html", data=data)

@app.route("/edit", methods=["POST"])
def edit():
    original_yt_name = request.form["original_YT_Name"]
    yt_name = request.form["YT_Name"]
    leds_colour = request.form["Leds_colour"]
    leds = request.form["Leds"]

    # Load and update data
    data = load_data()
    for entry in data:
        if entry["YT_Name"] == original_yt_name:
            entry["YT_Name"] = yt_name
            entry["Leds_colour"] = leds_colour
            entry["Leds"] = leds
            break
    save_data(data)

    return redirect(url_for("editor"))

@app.route("/delete", methods=["POST"])
def delete():
    yt_name = request.json.get("YT_Name")

    # Load data and filter out the entry with the given YT_Name
    data = load_data()
    data = [entry for entry in data if entry["YT_Name"] != yt_name]

    # Save the updated data back to the JSON file
    save_data(data)

    return jsonify({"status": "success"})

@app.route("/trigger_leds", methods=["POST"])
def trigger_leds():
    try:
        print("DEBUG: trigger_leds endpoint called")
        if os.path.exists(PLAQUES_FILE):
            with open(PLAQUES_FILE, 'r') as f:
                plaques = json.load(f)
                print(f"DEBUG: Loaded {len(plaques)} plaques from file")
        else:
            plaques = []
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
    if os.path.exists(PLAQUES_FILE):
        with open(PLAQUES_FILE, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify([])

@app.route('/plaques', methods=['POST'])
def save_plaques():
    data = request.get_json()
    with open(PLAQUES_FILE, 'w') as f:
        json.dump(data, f, indent=2)
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