import os
import traceback
import pygame
import time
import threading
import queue
import pyttsx3
import atexit

# Initialize the TTS queue
tts_queue = queue.Queue()
stop_event = threading.Event()

def create_engine():
    """Create a new pyttsx3 engine instance."""
    engine = pyttsx3.init()
    engine.setProperty("voice", 'HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices\Tokens\TTS_MS_EN-US_DAVID_11.0')
    return engine

def _tts_worker():
    """Worker thread to process TTS requests from the queue."""
    while True:
        item = tts_queue.get()  # Get the next item from the queue
        if item is None:  # Stop signal
            break

        text, newtts = item  # Unpack the text and newtts flag
        try:
            if stop_event.is_set():
                continue

            print(f"Processing text: {text}, newtts={newtts}")
            
            if newtts:
                _play_newtts(text)
            else:
                _play_oldtts(text)

        except Exception as e:
            print(f"Error during TTS playback: {e}")
        finally:
            tts_queue.task_done()


def gotts(text, newtts=True):
    """Add a TTS request to the queue with a 'newtts' flag."""
    tts_queue.put((text, newtts))  # Queue the text with the newtts attribute


def stop_tts_worker():
    """Gracefully stop the TTS worker thread."""
    tts_queue.put(None)  # Signal the thread to stop
    _worker_thread.join()  # Wait for the worker thread to exit
    print("TTS worker stopped gracefully.")


def _play_oldtts(text_to_say, session="default"):
    """Convert text to speech and play it without blocking."""
    if stop_event.is_set():
        return

    wav_path = f"./audio/{session}.wav"

    try:
        os.makedirs("./audio", exist_ok=True)

        # Run the speech synthesis command
        command = f'say.exe -w "{wav_path}" "[:PHONE ON]{text_to_say}"'
        os.system(command)

        pygame.mixer.init()
        pygame.mixer.music.load(wav_path)
        pygame.mixer.music.play()

        _wait_for_audio()

    except Exception as e:
        traceback.print_exc()

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
