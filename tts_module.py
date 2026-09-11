import os
import subprocess
import traceback
import pygame
import time
import threading
import queue
import pyttsx3
import atexit
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAY_EXE = BASE_DIR / "say.exe"
AUDIO_DIR = BASE_DIR / "audio"

# One queue for TTS and sound effects so they play in order and never overlap
tts_queue = queue.Queue()
stop_event = threading.Event()
pause_event = threading.Event()

def create_engine():
    """Create a new pyttsx3 engine instance."""
    engine = pyttsx3.init()
    engine.setProperty("voice", r'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_EN-US_DAVID_11.0')
    return engine

def _tts_worker():
    """Worker thread that plays queued TTS messages and sound effects one at a time."""
    while True:
        item = tts_queue.get()  # Get the next item from the queue
        if item is None:  # Stop signal
            break

        kind, payload, newtts = item
        try:
            # Wait while paused, but allow stop to interrupt
            while pause_event.is_set() and not stop_event.is_set():
                time.sleep(0.1)

            if stop_event.is_set():
                continue

            if kind == "sound":
                print(f"Playing sound: {Path(payload).name}")
                _play_audio_file(payload)
            else:
                print(f"Processing text: {payload}, newtts={newtts}")
                if newtts:
                    _play_newtts(payload)
                else:
                    _play_oldtts(payload)

        except Exception as e:
            print(f"Error during TTS playback: {e}")
        finally:
            tts_queue.task_done()


def gotts(text, newtts=True):
    """Add a TTS request to the queue with a 'newtts' flag."""
    tts_queue.put(("tts", text, newtts))


def queue_sound(sound_path):
    """Queue a sound effect to play after whatever is already queued."""
    tts_queue.put(("sound", str(sound_path), None))


def stop_tts_worker():
    """Gracefully stop the TTS worker thread."""
    tts_queue.put(None)  # Signal the thread to stop
    _worker_thread.join()  # Wait for the worker thread to exit
    print("TTS worker stopped gracefully.")


def _play_oldtts(text_to_say, session="default"):
    """Convert text to speech and play it without blocking."""
    if stop_event.is_set():
        return

    wav_path = AUDIO_DIR / f"{session}.wav"

    try:
        os.makedirs(AUDIO_DIR, exist_ok=True)

        # Pass chat text as a single argument with no shell, so quotes or
        # characters like & in a message can't run other commands
        subprocess.run(
            [str(SAY_EXE), "-w", str(wav_path), f"[:PHONE ON]{text_to_say}"],
            cwd=BASE_DIR,
            check=False,
        )

        _play_audio_file(wav_path)

    except Exception as e:
        traceback.print_exc()


def _play_audio_file(path):
    """Play a WAV or MP3 file and wait until it finishes or is skipped."""
    if stop_event.is_set():
        return

    pygame.mixer.init()
    pygame.mixer.music.load(str(path))
    pygame.mixer.music.play()
    _wait_for_audio()

def _play_newtts(text_to_say, session="default"):
    """Convert text to speech and play it without blocking."""
    if stop_event.is_set():
        return

    try:
        engine = create_engine()
        engine.say(text_to_say)
        engine.runAndWait()  # Speak the text

    except Exception as e:
        traceback.print_exc()

def _wait_for_audio():
    """Wait for audio to finish playing and release the file."""
    while pygame.mixer.music.get_busy():
        if stop_event.is_set():
            pygame.mixer.music.stop()
            break
        time.sleep(0.1)

    pygame.mixer.quit()

def skip_current_tts():
    """Stop the current audio without clearing the entire queue."""
    stop_event.set()  # Signal to stop current audio
    if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
        pygame.mixer.music.stop()  # Stop current audio if active
    try:
        engine = create_engine()
        engine.stop()
    except:
        print("Error stopping Engine (this could be fine)")
    stop_event.clear()  # Allow the next audio to play


def pause_queue():
    """Pause processing of the TTS queue without clearing items."""
    pause_event.set()
    return True


def resume_queue():
    """Resume processing of the TTS queue."""
    pause_event.clear()
    return False


def toggle_pause():
    """Toggle pause state and return the new paused status."""
    if pause_event.is_set():
        resume_queue()
    else:
        pause_queue()
    return pause_event.is_set()


def is_paused() -> bool:
    return pause_event.is_set()


def clear_queue():
    """Stop current audio and clear the remaining TTS queue."""
    stop_event.set()  # Signal to stop current audio
    if pygame.mixer.get_init():
        pygame.mixer.music.stop()  # Stop current audio if active
    
    # Clear the queue while keeping the worker thread alive
    with tts_queue.mutex:
        tts_queue.queue.clear()
    
    stop_event.clear()  # Allow the next audio to play




# Start the TTS worker thread
_worker_thread = threading.Thread(target=_tts_worker, daemon=True)
_worker_thread.start()

# Register cleanup for the worker thread
atexit.register(stop_tts_worker)



if __name__ == "__main__":
    gotts("Pyro. Said. This is the first test message.")
    time.sleep(1)
    gotts("[:PHONE ON][mah<200,31>][rih<200,34>][teh<200,31>][pow<400,29>][ney<600,34>]")
    time.sleep(1)
    gotts("This is the third test message.")
    
    # Clear the queue or stop TTS at any point
    # clear_queue()

    # Keep the script running to process the queue
    while not tts_queue.empty():
        time.sleep(0.5)

    print("All messages processed. Exiting.")
