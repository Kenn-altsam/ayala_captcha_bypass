#
# Python Captcha Bypass
# https://github.com/threadexio/python-captcha-bypass
#
#	MIT License
#
# --- MODIFIED FOR KGD.GOV.KZ ---

from enum import Enum
from typing import Tuple
from pydub import AudioSegment
import speech_recognition as sr
import tempfile
import requests
import time
import os
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class status(Enum):
    SUCCESS = 0
    UNKNOWN = 1
    RATELIMITED = 2
    TIMEOUT = 3
    NO_CHALLENGE = 4  # Added status for when challenge is not needed

class NotExistent(Exception):
    err = None
    def __init__(self, error, *args: object) -> None:
        super().__init__(*args)
        self.err = error

def solve_captcha(driver, t: int = 10):
    """Solve the given captcha.
    This version is adapted to handle cases where no audio challenge appears.

    Args:
        driver (WebDriver): The Selenium WebDriver instance.
        t (int, optional): Page load timeout in seconds. Defaults to 10.

    Returns:
        Tuple(status, str): A tuple containing the status and the recognized text (if any).
    """

    ret: Tuple[status, str] | None = None
    tmp_dir = tempfile.gettempdir()
    mp3_file = os.path.join(tmp_dir, "_tmp.mp3")
    wav_file = os.path.join(tmp_dir, "_tmp.wav")
    tmp_files = [mp3_file, wav_file]
    wait = WebDriverWait(driver, t)

    try:
        print("Attempting to solve captcha...")

        # Wait for the reCAPTCHA iframe to be present and switch to it
        print("Switching to reCAPTCHA iframe...")
        iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[title="reCAPTCHA"]')))
        driver.switch_to.frame(iframe)
        print("Successfully switched to reCAPTCHA iframe")

        # Click the checkbox
        print("Looking for checkbox...")
        checkbox = wait.until(EC.element_to_be_clickable((By.CLASS_NAME, "recaptcha-checkbox-border")))
        checkbox.click()
        print("Clicked checkbox")

        # --- NEW LOGIC: Check if captcha is solved without a challenge ---
        time.sleep(2)  # Wait for potential verification
        try:
            # Switch back to main content to check the response textarea
            driver.switch_to.default_content()
            response_textarea = driver.find_element(By.ID, "g-recaptcha-response")
            if response_textarea.get_attribute('value'):
                print("Captcha solved without a visual/audio challenge!")
                return (status.SUCCESS, "Passed without challenge")
        except NoSuchElementException:
            # Expected if the check fails; continue to the audio challenge
            print("Visual/audio challenge is required.")

        # Ensure we are back to the main content before proceeding
        driver.switch_to.default_content()
        # --- END OF NEW LOGIC ---

        # Wait for and switch to the challenge iframe
        print("Looking for challenge iframe...")
        challenge_frame = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[title*="recaptcha challenge"]')))
        driver.switch_to.frame(challenge_frame)
        print("Switched to challenge iframe")

        # Click audio button
        print("Looking for audio button...")
        audio_button = wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-audio-button")))
        audio_button.click()
        print("Clicked audio button")

        # Get the download link
        print("Looking for download link...")
        download_link = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "rc-audiochallenge-tdownload-link")))
        if not download_link:
            print("No download link found")
            raise NotExistent(status.RATELIMITED)
        print("Found download link")

        # Download the audio file
        print("Downloading audio file...")
        link = download_link.get_attribute("href")
        with open(mp3_file, "wb") as f:
            r = requests.get(link, allow_redirects=True)
            f.write(r.content)
        print("Downloaded audio file")

        # Convert to wav
        print("Converting to WAV...")
        AudioSegment.from_mp3(mp3_file).export(wav_file, format="wav")
        print("Converted to WAV")

        # Recognize speech
        print("Recognizing speech...")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_file) as source:
            recorded_audio = recognizer.listen(source)
            text = recognizer.recognize_google(recorded_audio, language="en-US")  # Specify language for better accuracy
        print(f"Recognized text: {text}")

        # Type out the answer
        print("Entering answer...")
        audio_response = wait.until(EC.presence_of_element_located((By.ID, "audio-response")))
        audio_response.send_keys(text)
        time.sleep(1)
        print("Entered answer")

        # Click verify
        print("Looking for verify button...")
        verify_button = wait.until(EC.element_to_be_clickable((By.ID, "recaptcha-verify-button")))
        verify_button.click()
        time.sleep(2)
        print("Clicked verify button")

        ret = (status.SUCCESS, text)

    except TimeoutException:
        # This can happen if the challenge was passed immediately after checkbox click
        # Or if the page is too slow. We check the response again.
        print("Timeout occurred. Checking if captcha was solved anyway...")
        try:
            driver.switch_to.default_content()
            response_textarea = driver.find_element(By.ID, "g-recaptcha-response")
            if response_textarea.get_attribute('value'):
                print("Captcha was solved despite timeout.")
                ret = (status.SUCCESS, "Passed after timeout check")
            else:
                print("Captcha not solved after timeout.")
                ret = (status.TIMEOUT, "")
        except Exception:
            ret = (status.TIMEOUT, "")

    except NotExistent as e:
        print(f"Not existent error: {e}")
        ret = (e.err, "")

    except Exception as e:
        print(f"An unexpected error occurred in solve_captcha: {e}")
        ret = (status.UNKNOWN, "")

    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass  # Ignore errors if already in default content
        __cleanup(tmp_files)
        return ret if ret is not None else (status.UNKNOWN, "")


def __cleanup(files: list):
    """Remove temporary files if they exist."""
    for x in files:
        if os.path.exists(x):
            os.remove(x)
