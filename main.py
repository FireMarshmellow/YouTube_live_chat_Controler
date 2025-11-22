import os
import threading
import time
from typing import Optional

import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from twitchio.ext import commands

import commandhandler
import plaque_board_controller
from app import app as flask_app
from storage import find_plaque, load_commands, load_secrets, save_secrets
from tts_module import gotts

CHAT_POLL_INTERVAL = 5  # seconds between YouTube chat polls
def handle_message(display_name: str, message_text: str, is_superchat: bool = False) -> None:
    """Route incoming chat messages to commands, LEDs, and TTS."""
    if not display_name or not message_text:
        return

    normalized_text = message_text.strip()
    normalized_lower = normalized_text.lower()

    if find_plaque(display_name):
        threading.Thread(
            target=plaque_board_controller.set_leds_for_user,
            args=(display_name, 5),
            daemon=True,
        ).start()

    if normalized_lower.startswith("!dec"):
        dec_text = normalized_text[5:].strip()
        if dec_text:
            ttstext = f"{display_name} said: {dec_text}"
            threading.Thread(target=gotts, args=(ttstext, False), daemon=True).start()
        return

    commands = load_commands()
    for base_command in commands.keys():
        if base_command in normalized_lower:
            commandhandler.execute_command(normalized_lower, display_name, is_superchat)
            return

    ttstext = f"{display_name} said: {normalized_text}"
    threading.Thread(target=gotts, args=(ttstext,), daemon=True).start()



class TwitchBot(commands.Bot):
    def __init__(self, token, channel):
        super().__init__(token=token, prefix="!", initial_channels=[channel])

    async def event_ready(self):
        print(f"Logged in as {self.nick}")

    async def event_message(self, message):
        if message.author is None or message.author.name == self.nick:
            return
        handle_message(message.author.name, message.content)


def refresh_twitch_oauth_token(secrets: dict) -> Optional[str]:
    """Refresh the Twitch token using the stored refresh token."""
    client_id     = secrets.get("TWITCH_CLIENT_ID")
    client_secret = secrets.get("TWITCH_CLIENT_SECRET")
    refresh_token = secrets.get("TWITCH_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        print("Twitch OAuth refresh credentials missing, skipping refresh.")
        return secrets.get("TWITCH_OAUTH_TOKEN")

    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret
    }

    resp = requests.post(url, params=params, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        new_access  = data["access_token"]
        new_refresh = data.get("refresh_token")
        print("Twitch token refreshed successfully.")
        # update and persist
        secrets["TWITCH_OAUTH_TOKEN"]   = new_access
        if new_refresh:
            secrets["TWITCH_REFRESH_TOKEN"] = new_refresh
        save_secrets(secrets)
        return new_access
    else:
        print(f"Failed to refresh Twitch token: {resp.status_code} {resp.text}")
        return secrets.get("TWITCH_OAUTH_TOKEN")

def listen_to_live_chat(live_chat_id: str) -> None:
    """Continuously poll YouTube live chat and forward the messages."""
    secrets = load_secrets()
    youtube = build('youtube', 'v3', developerKey=secrets['api_key'])
    request = youtube.liveChatMessages().list(
        liveChatId=live_chat_id,
        part='id,snippet,authorDetails',
    )
    processed_message_ids = set()

    while request:
        try:
            response = request.execute()
        except HttpError as e:
            print(f"Error retrieving live chat messages: {e}")
            break

        for item in response.get('items', []):
            message_id = item['id']
            if message_id in processed_message_ids:
                continue

            processed_message_ids.add(message_id)
            message_text = item['snippet']['displayMessage']
            display_name = item['authorDetails']['displayName']
            is_superchat = item['snippet'].get('superChatDetails') is not None
            handle_message(display_name, message_text, is_superchat)

        request = youtube.liveChatMessages().list_next(request, response)
        if not request:
            print("No more live chat messages available.")
            break

        time.sleep(CHAT_POLL_INTERVAL)

def get_live_video_id(api_key: str, channel_id: str) -> Optional[str]:
    """
    Fetches the active live video ID from a given YouTube channel.
    Returns None if no live stream is found.
    """
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        request = youtube.search().list(
            part="id",
            channelId=channel_id,
            eventType="live",  # Only active live streams
            type="video",
            maxResults=1
        )
        response = request.execute()

        if "items" in response and len(response["items"]) > 0:
            return response["items"][0]["id"]["videoId"]
    except HttpError as e:
        print(f"Error fetching live video ID: {e}")
    
    return None  # No live video found

def get_live_chat_id(video_id: str, secrets: dict) -> Optional[str]:
    """
    Fetch the live chat ID for the given video.
    Falls back to API_KEY_Backup if the primary key fails.
    """
    api_keys = [secrets['api_key'], secrets['api_key_backup']]
    last_exception = None

    for api_key in api_keys:
        try:
            youtube = build("youtube", "v3", developerKey=api_key)
            request = youtube.videos().list(part="liveStreamingDetails", id=video_id)
            response = request.execute()

            live_chat_id = (
                response.get("items", [])[0]
                .get("liveStreamingDetails", {})
                .get("activeLiveChatId")
            )

            if live_chat_id:
                #print(f"Successfully retrieved live chat ID using API key: {api_key}")
                return live_chat_id

        except HttpError as e:
            last_exception = e
            #print(f"API key {api_key} failed with error: {e}")
        except Exception as e:
            last_exception = e
            #print(f"Unexpected error with API key {api_key}: {e}")

    # If all API keys fail
    if last_exception:
        print(f"All API keys failed. Last error: {last_exception}")
    
    return None

def input_with_timeout(prompt: str, timeout: int = 10) -> Optional[str]:
    result = [None]

    def get_input():
        result[0] = input(prompt).strip()

    input_thread = threading.Thread(target=get_input)
    input_thread.daemon = True
    input_thread.start()
    input_thread.join(timeout)
    
    if input_thread.is_alive():
        print("\nTimeout reached. Continuing...")
        return None
    return result[0]

if __name__ == '__main__':
    if not os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        secrets = load_secrets()
        
        refreshed_token = refresh_twitch_oauth_token(secrets)
        secrets["TWITCH_OAUTH_TOKEN"] = refreshed_token

        # Try to get an active live video ID automatically
        video_id = get_live_video_id(secrets['api_key'], secrets['channel_id'])

        if not video_id:
            print("No active live stream found.")
            video_id = input_with_timeout("Please enter a video ID manually: ", timeout=10)

        if not video_id:
            print("No valid video ID provided; skipping YouTube chat.")
        else:
            live_chat_id = get_live_chat_id(video_id, secrets)

            if live_chat_id:
                print(f"Found live chat for video {video_id}. Listening for messages...")
                threading.Thread(target=listen_to_live_chat, args=(live_chat_id,), daemon=True).start()
            else:
                print("Live chat not found for this video. Disable Youtube Chat.")

        # Start Twitch bot
        if refreshed_token:
            twitch_bot = TwitchBot(refreshed_token, secrets["TWITCH_CHANNEL"])
            threading.Thread(target=twitch_bot.run, daemon=True).start()
        else:
            print("No Twitch token available; skipping Twitch bot startup.")
    # Run the Flask app
    # flask_app = Flask(__name__)
    # flask_app.secret_key = 'supersecretkey'
    flask_app.run()
