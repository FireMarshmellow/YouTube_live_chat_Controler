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
    response = requests.post(api_endpoint, json=payload)

    # Check if the request was successful
    if response.status_code == 200:
        #print(f"Set color {color} for LEDs {led_indices_new} successfully!")
        pass
    else:
        #print(f"Failed to set color for LEDs {led_indices_new}. Status code: {response.status_code}")
        return False
    
    time.sleep(timehere)
    
    # Construct the payload to turn off the LEDs
    for index in led_indices_new:
        payload["seg"]["i"].extend([index, "000000"])

    # Send the API request to turn off all LEDs
    response = requests.post(api_endpoint, json=payload)

    # Check if the request was successful
    if response.status_code == 200:
        #print("Turned off all LEDs successfully!")
        return True
    else:
        #print(f"Failed to turn off all LEDs. Status code: {response.status_code}")
        return False


#set_leds('86,85,84,99,100,101', "#f6de15",5)