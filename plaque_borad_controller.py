import requests
import time
import pyttsx3
import Secrets

def set_leds(led_indices, color,timehere):
    
    led_indices_new = list(map(int, led_indices.split(',')))
    api_endpoint = f"" + str(Secrets.BOARD_IP) + "/json/state"
    payload = {
        "seg": {
            "id": 0,
            "i": []
        }
    }

    # Construct the payload to set the color of each LED
    for index in led_indices_new:
        payload["seg"]["i"].extend([index, color[1:]])

    # Send the API request to set the colors of the LEDs
    try:
        response = requests.post(api_endpoint, json=payload)
        response.raise_for_status()  # Raise HTTPError for bad responses
    except requests.exceptions.RequestException as e:
        print(f"Failed to set color for LEDs {led_indices_new}. Error: {e}")
        return False
    else:
        #print(f"Set color {color} for LEDs {led_indices_new} successfully!")
        pass
    
    time.sleep(timehere)
    
    # Payload to return to previous effect
    payload = {
        "seg": {
            "id": 0,
            "frz": False
        }
    }

    # Send the API request to turn off all LEDs
    try:
        response = requests.post(api_endpoint, json=payload)
        response.raise_for_status()  # Raise HTTPError for bad responses
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return False
    else:
        #print(f"Turned off the leds")
        return True


#set_leds('86,85,84,99,100,101', "#f6de15",5)
