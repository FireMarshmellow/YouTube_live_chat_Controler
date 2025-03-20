import requests
import time
import json
import os

SECRETS_FILE = 'secrets.json'

# Function to load data from JSON
def load_secrets():
    if not os.path.exists(SECRETS_FILE):
        return []  # Return empty list if file does not exist
    with open(SECRETS_FILE, "r") as file:
        return json.load(file)


def send_request_with_retry(api_endpoint, payload, max_retries=3, delay=1):
    for attempt in range(max_retries):
        try:
            response = requests.post(api_endpoint, json=payload)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            if 'response' in locals() and response is not None and response.status_code == 503:
                print(f"503 error, retrying... ({attempt + 1}/{max_retries})")
                time.sleep(delay)
            else:
                print(f"Request failed: {e}")
                return None
    print("Max retries reached. Giving up.")
    return None



def set_leds(led_indices, color, timehere):
    secrets = load_secrets()
    led_indices_new = list(map(int, led_indices.split(",")))
    api_endpoint = f"" + str(secrets['board_ip']) + "/json/state"
    payload = {"seg": {"id": 0, "i": []}}

    # Convert the color tuple (r, g, b) to a hex string without the '#' prefix.
    hex_color = '{:02x}{:02x}{:02x}'.format(*color)
    # Construct the payload to set the color of each LED.
    for index in led_indices_new:
        payload["seg"]["i"].extend([index, hex_color])

    response = send_request_with_retry(api_endpoint, payload)
    if response is None:
        return False

    time.sleep(timehere)

    # Turn off the LEDs
    payload = {"seg": {"id": 0, "frz": False}}
    response = send_request_with_retry(api_endpoint, payload)
    return response is not None


def set_leds_for_user(display_name, duration=5):
    """Trigger LEDs for a user based on their display name"""
    try:
        # Load plaques from file
        if os.path.exists('plaques.json'):
            with open('plaques.json', 'r') as f:
                plaques = json.load(f)
        else:
            return False

        # Find matching plaque
        matching_plaque = None
        for plaque in plaques:
            if plaque.get('YT_Name', '').lower() == display_name.lower():
                matching_plaque = plaque
                break

        if matching_plaque:
            # Get color and convert from hex
            color = matching_plaque.get('Leds_colour', '#FFFFFF')
            color = color.lstrip('#')
            r, g, b = tuple(int(color[i:i+2], 16) for i in (0, 2, 4))

            # Get LED indices
            leds = matching_plaque.get('Leds', '')
            #print(f"Triggering LEDs for {display_name} - Color: #{color}, Leds: {leds}")

            # Trigger the LEDs
            return set_leds(leds, (r, g, b), duration)
    except Exception as e:
        print(f"Error triggering LEDs for {display_name}: {e}")
        return False
