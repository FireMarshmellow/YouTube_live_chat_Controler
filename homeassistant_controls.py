import requests
import time

from storage import load_secrets


def _get_connection_details():
    secrets = load_secrets()
    access_token = secrets.get("access_token")
    ha_url = secrets.get("ha_url")
    if not access_token or not ha_url:
        raise RuntimeError("Home Assistant credentials are missing from secrets.json.")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    return ha_url, headers

def call_ha_service(service, data):
    ha_url, headers = _get_connection_details()
    url = f"{ha_url}/api/services/{service}"
    response = requests.post(url, headers=headers, json=data, timeout=10)
    if response.status_code == 200:
        print(f"Service '{service}' called successfully.")
    else:
        print(f"Error calling service '{service}': {response.text}")

def Bubbles():
    entity_id = 'button.esphome_web_13e1fc_bubble_burst'
    print("Turning on the bubble machine...")
    call_ha_service('button/press', {"entity_id": entity_id})

def Birthdaypopper():
    entity_id = 'switch.happpy_bday_celebrate'
    print("Turning on the celebrate machine...")
    call_ha_service('switch/turn_on', {"entity_id": entity_id})

def Birthdaycandle():
    entity_id = 'switch.happpy_bday_blow'
    print("Turning on the blow machine...")
    call_ha_service('switch/turn_on', {"entity_id": entity_id})

def adjust_desk_height(desired_height):
    STOP_ENTITY_ID = "over.esphome_web_fdf034_desk"
    SET_HEIGHT_ENTITY_ID = "number.esphome_web_fdf034_desk_height"

    def control_desk(stop_entity_id, set_height_entity_id, height):
        print("Stopping the desk...")
        call_ha_service('cover/stop_cover', {"entity_id": stop_entity_id})
        time.sleep(1)  # Wait for a moment before setting the height

        print("Setting the desk height...")
        call_ha_service('number/set_value', {"entity_id": set_height_entity_id, "value": height})

    # Call the control_desk function twice with a 1-second sleep between the calls
    control_desk(STOP_ENTITY_ID, SET_HEIGHT_ENTITY_ID, desired_height)
    time.sleep(1)
    control_desk(STOP_ENTITY_ID, SET_HEIGHT_ENTITY_ID, desired_height)

def PistonDown():
    entity_id = 'button.piston_move_down'
    print("Setting piston to bottom (zero)...")
    call_ha_service('button/press', {"entity_id": entity_id})

def PistonUp():
    entity_id = 'button.piston_go_to_top'
    print("Moving piston to top...")
    call_ha_service('button/press', {"entity_id": entity_id})
