import os
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Optional

import grpc
import requests
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from twitchio.ext import commands

import commandhandler
import currency
import patron_blinker
import stream_list_pb2
import stream_list_pb2_grpc
from app import app as flask_app
from storage import find_plaque, load_commands, load_secrets, save_secrets
from tts_module import gotts
from youtube_utils import verify_youtube_keys

YOUTUBE_GRPC_TARGET = "dns:///youtube.googleapis.com:443"
STREAM_RECONNECT_DELAY = 1  # seconds before reopening a chat stream the server closed
STREAM_RETRY_MAX_DELAY = 60  # cap for the backoff after connection errors
RETRYABLE_STREAM_CODES = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.INTERNAL,
}


def build_youtube_client(api_key: str):
    return build("youtube", "v3", developerKey=api_key)


def should_switch_api_key(error: grpc.RpcError, key_count: int) -> bool:
    """Determine if the backup API key should be used after a failure."""
    if key_count <= 1:
        return False
    if error.code() in (grpc.StatusCode.PERMISSION_DENIED, grpc.StatusCode.RESOURCE_EXHAUSTED):
        return True
    return "quota" in (error.details() or "").lower()


@dataclass
class SuperChat:
    amount_micros: int     # 1,750,000 micros = 1.75
    currency: str          # ISO 4217 code, e.g. "USD"
    amount_display: str    # YouTube's own formatting, e.g. "$1.75"


def describe_amount(superchat: SuperChat) -> str:
    """The Super Chat amount in pounds, or YouTube's original amount if it can't be converted."""
    pounds = currency.to_gbp(superchat.amount_micros / 1_000_000, superchat.currency)
    return currency.format_gbp(pounds) if pounds is not None else superchat.amount_display


def handle_message(
    display_name: str,
    message_text: str,
    is_superchat: bool = False,
    superchat: SuperChat | None = None,
) -> None:
    """
    Route incoming chat messages to commands, LEDs, and TTS. Errors are logged
    and swallowed so one bad message can't stop the chat listener.
    """
    try:
        _route_message(display_name, message_text, is_superchat or superchat is not None, superchat)
    except Exception:
        print(f"Error handling message from {display_name!r}:")
        traceback.print_exc()


def _route_message(display_name: str, message_text: str, is_superchat: bool, superchat: SuperChat | None) -> None:
    # A Super Chat can have no message, but still gets announced
    if not display_name or not (message_text or superchat):
        return

    normalized_text = (message_text or "").strip()
    normalized_lower = normalized_text.lower()
    spoken_name = display_name.lstrip("@")  # YouTube handles arrive as "@name"
    donation = f"{spoken_name} donated {describe_amount(superchat)}" if superchat else None

    plaque = find_plaque(display_name)
    if plaque:
        threading.Thread(
            target=patron_blinker.highlight_plaque,
            args=(plaque,),
            daemon=True,
        ).start()

    if normalized_lower.startswith("!dec"):
        if donation:
            gotts(donation)
        dec_text = normalized_text[5:].strip()
        if dec_text:
            # Queued directly (it's instant) so speech and sound effects keep chat order
            gotts(f"{spoken_name} said: {dec_text}", False)
        return

    commands = load_commands()
    for base_command in commands.keys():
        if base_command in normalized_lower:
            if donation:
                gotts(donation)
            commandhandler.execute_command(normalized_lower, display_name, is_superchat)
            return

    if donation:
        gotts(f"{donation} and says {normalized_text}" if normalized_text else donation)
    else:
        gotts(f"{spoken_name} said: {normalized_text}")



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

def listen_to_live_chat(live_chat_id: str, api_keys: list[str], skip_first_batch: bool = True) -> None:
    """
    Stream YouTube live chat over gRPC (liveChatMessages.streamList) and forward
    the messages. The server pushes new messages over one open connection, so
    quota is spent per connection instead of per poll.
    """
    if not api_keys:
        print("No YouTube API keys configured; cannot listen to chat.")
        return

    current_key_index = 0
    processed_message_ids = set()
    next_page_token = None
    first_batch = True
    retry_delay = STREAM_RECONNECT_DELAY

    with grpc.secure_channel(YOUTUBE_GRPC_TARGET, grpc.ssl_channel_credentials()) as channel:
        stub = stream_list_pb2_grpc.V3DataLiveChatMessageServiceStub(channel)

        while True:
            request = stream_list_pb2.LiveChatMessageListRequest(
                live_chat_id=live_chat_id,
                part=["id", "snippet", "authorDetails"],
                page_token=next_page_token,
            )
            metadata = (("x-goog-api-key", api_keys[current_key_index]),)

            try:
                for response in stub.StreamList(request, metadata=metadata):
                    retry_delay = STREAM_RECONNECT_DELAY

                    if first_batch and skip_first_batch:
                        # The first response is the chat history; prime the cache so it isn't replayed
                        for item in response.items:
                            processed_message_ids.add(item.id)
                    else:
                        for item in response.items:
                            if item.id in processed_message_ids:
                                continue

                            processed_message_ids.add(item.id)
                            if item.snippet.HasField("super_chat_details"):
                                details = item.snippet.super_chat_details
                                handle_message(
                                    item.author_details.display_name,
                                    details.user_comment,
                                    superchat=SuperChat(details.amount_micros, details.currency, details.amount_display_string),
                                )
                            else:
                                handle_message(item.author_details.display_name, item.snippet.display_message)
                    first_batch = False

                    if response.next_page_token:
                        next_page_token = response.next_page_token

                    if response.offline_at:
                        print(f"YouTube stream went offline at {response.offline_at}; stopping chat listener.")
                        return
            except grpc.RpcError as e:
                if should_switch_api_key(e, len(api_keys)):
                    current_key_index = (current_key_index + 1) % len(api_keys)
                    print(
                        f"Switched to backup YouTube API key (index {current_key_index}) "
                        f"after error: {e.code().name} {e.details()}"
                    )
                    time.sleep(STREAM_RECONNECT_DELAY)
                    continue

                if e.code() in RETRYABLE_STREAM_CODES:
                    print(
                        f"YouTube chat stream dropped ({e.code().name}: {e.details()}); "
                        f"reconnecting in {retry_delay}s."
                    )
                    time.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, STREAM_RETRY_MAX_DELAY)
                    continue

                print(f"Error streaming live chat messages: {e.code().name} {e.details()}")
                break

            if not next_page_token:
                print("No more live chat messages available.")
                break

            # The server closed the stream normally; resume from the last page token
            time.sleep(STREAM_RECONNECT_DELAY)

def _search_video_by_event(
    channel_id: str, api_keys: list[str], event_type: str
) -> Optional[str]:
    """Return the first video ID for the requested event type."""
    last_error = None
    for api_key in api_keys:
        try:
            youtube = build_youtube_client(api_key)
            request = youtube.search().list(
                part="id",
                channelId=channel_id,
                eventType=event_type,
                type="video",
                maxResults=1,
                order="date",
            )
            response = request.execute()
            items = response.get("items", [])
            if items:
                return items[0]["id"]["videoId"]
        except HttpError as exc:
            last_error = exc
            print(f"Failed to fetch {event_type} broadcast with current key: {exc}")
    if last_error:
        print(f"Exhausted API keys; unable to find {event_type} broadcast.")
    return None


def get_live_video_id(channel_id: str, api_keys: list[str]) -> Optional[str]:
    """
    Fetches the active live video ID from a given YouTube channel.
    Falls back to the next scheduled broadcast if nothing is currently live.
    """
    if not api_keys:
        print("No API keys available for fetching live video ID.")
        return None

    live_video = _search_video_by_event(channel_id, api_keys, "live")
    if live_video:
        return live_video

    print("No active stream found; looking for upcoming scheduled streams.")
    return _search_video_by_event(channel_id, api_keys, "upcoming")

def get_live_chat_id(video_id: str, api_keys: list[str]) -> Optional[str]:
    """
    Fetch the live chat ID for the given video.
    Falls back to API_KEY_Backup if the primary key fails.
    """
    if not api_keys:
        print("No API keys available for fetching live chat ID.")
        return None
    last_exception = None

    for api_key in api_keys:
        try:
            youtube = build_youtube_client(api_key)
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

        api_key_status = verify_youtube_keys(secrets)
        # The backup key is optional; use whichever keys verify
        api_keys: list[str] = []
        for key_name in ("api_key", "api_key_backup"):
            status = api_key_status[key_name]
            if status["ok"]:
                api_keys.append(secrets[key_name])
            else:
                print(f"YouTube key '{key_name}' not usable ({status['reason']}); skipping it.")

        # Try to get an active live video ID automatically
        video_id = None
        channel_id = secrets.get("channel_id")
        if not api_keys:
            print("Skipping YouTube chat setup until API keys verify successfully.")
        elif channel_id:
            video_id = get_live_video_id(channel_id, api_keys)
            if not video_id:
                print("No active live stream found.")
        else:
            print("No channel_id saved; add it on the Secrets page so your stream is found automatically.")

        if api_keys and not video_id:
            # Fall back to the video ID saved on the Secrets page if nothing is typed in
            video_id = input_with_timeout("Please enter a video ID manually: ", timeout=10) or secrets.get("video_id")
            if video_id:
                print(f"Using video ID {video_id}.")

        if not api_keys:
            print("No valid YouTube API keys available; skipping YouTube chat.")
        elif not video_id:
            print("No valid video ID provided; skipping YouTube chat.")
        else:
            live_chat_id = get_live_chat_id(video_id, api_keys)

            if live_chat_id:
                print(f"Found live chat for video {video_id}. Listening for messages...")
                threading.Thread(
                    target=listen_to_live_chat,
                    args=(live_chat_id, api_keys, True),
                    daemon=True,
                ).start()
            else:
                print("Live chat not found for this video. Disable Youtube Chat.")

        # Start Twitch bot
        if refreshed_token and secrets.get("TWITCH_CHANNEL"):
            twitch_bot = TwitchBot(refreshed_token, secrets["TWITCH_CHANNEL"])
            threading.Thread(target=twitch_bot.run, daemon=True).start()
        else:
            print("No Twitch token or channel available; skipping Twitch bot startup.")
    # Ambient patron animation on the LED board; chat highlights run on top of it
    patron_blinker.start_animation()
    threading.Thread(target=currency.preload_rates, daemon=True).start()

    # Run the Flask app
    # flask_app = Flask(__name__)
    # flask_app.secret_key = 'supersecretkey'
    flask_app.run()
