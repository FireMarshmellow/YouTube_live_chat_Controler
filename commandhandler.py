import re
import os
import time
from datetime import datetime, timedelta
from homeassistant_controls import Bubbles, adjust_desk_height
from sound_board import play_sound
import json

access_hierarchy = ["regular", "patron", "superchat"]
COMMANDS_FILE = 'commands.json'
DATA_FILE = "data.json"


def check_access(user_status, command_level):
    user_level = (
        access_hierarchy.index(user_status) if user_status in access_hierarchy else 0
    )
    command_level_index = (
        access_hierarchy.index(command_level)
        if command_level in access_hierarchy
        else 0
    )
    return user_level >= command_level_index

# Load commands from JSON file
def load_commands():
    with open(COMMANDS_FILE, 'r') as file:
        return json.load(file)

# Function to get access levels
def get_access_levels():
    return {
        "regular": 1,
        "patreon": 2,
        "superchat": 3,
    }

# Tracking command execution times
last_executed = {}

# Function to execute a command
def execute_command(command, display_name, is_superchat=False):
    commands = load_commands()
    user_access_level = get_user_access_level(display_name, is_superchat)

    command = command.strip().lower()

    if command.startswith('!desk'):
        base_command = '!desk'
    else:
        base_command = command.split()[0]  # Get the command without arguments

    # Check if the base command exists in commands.json
    if base_command in commands and commands[base_command]['enabled']:
        command_details = commands[base_command]

        # Access level check
        required_access_level = command_details['access_level']
        if get_access_levels()[user_access_level] < get_access_levels()[required_access_level]:
            print(f"User {display_name} does not have the required access level ({user_access_level}) for command {command} (requires {required_access_level}).")
            return

        # Timeout check
        current_time = time.time()
        if base_command in last_executed:
            time_elapsed = current_time - last_executed[base_command]
            if time_elapsed < command_details['timeout']:
                print(f"Command {command} is on timeout for {display_name}. Please wait {command_details['timeout'] - time_elapsed:.2f} seconds.")
                return

        # Execute the command
        print(f"Executing command {command} from {display_name}")
        perform_command_action(command, display_name)
        last_executed[base_command] = current_time
    else:
        print(f"Command '{command}' is not enabled or does not exist.")

# Function to perform the command action (like playing a sound or controlling devices)
def perform_command_action(command, displayname):
    if command.startswith("!sound_"):
        sound_name = command.split("!sound_")[1]
        sound_name = sound_name.lower()
        print(f"Attempting to play sound: {sound_name}")
        play_sound(sound_name)
    elif command == "!bubbles":
        Bubbles()
    elif command == "!blow":
        if displayname == 'pyrohouz':
            Bubbles()
    elif command.startswith("!desk"):
        try:
            # Remove the command part and extract the number
            match = re.match(r'!desk[_\s]*(\d+)', command)
            if match:
                desired_height = int(match.group(1))
            else:
                print("No valid height specified for desk command.")
                return
            if 71 <= desired_height <= 120:
                print(f"Adjusting desk to height: {desired_height} cm")
                adjust_desk_height(desired_height)
            else:
                print(f"Desired height {desired_height} is out of range. Must be between 71 and 120 cm.")
        except ValueError:
            print(f"Invalid desk height specified in command: {command}")
    else:
        print(f"No action defined for command: {command}")

def load_data():
    if not os.path.exists(DATA_FILE):
        return []  # Return empty list if file does not exist
    with open(DATA_FILE, "r") as file:
        return json.load(file)

def load_supporters():
    # Assuming supporters data is stored in plaques.json.
    # If you have another file for patreon users, update the path accordingly.
    with open("plaques.json", "r") as file:
        return json.load(file)

# Function to get user access level
def get_user_access_level(display_name, is_superchat=False):
    if is_superchat:  # Bypass for superchat if desired
        return "superchat"

    display_name_lower = display_name.lower()
    supporters = load_supporters()
    for supporter in supporters:
        # Check against both keys. If a second username was added, include it.
        yt_name = supporter.get("YT_Name", "").lower()
        twitchusername = supporter.get("twitchusername", "").lower()
        if display_name_lower in (yt_name, twitchusername):
            return "patreon"
    return "regular"
