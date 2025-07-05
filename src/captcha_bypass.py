#
# Python Captcha Bypass
# https://github.com/threadexio/python-captcha-bypass
#
#	MIT License
#

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

class status(Enum):
    SUCCESS = 0
    UNKNOWN = 1
    RATELIMITED = 2
    TIMEOUT = 3

class NotExistent(Exception):
    """
    This exception is used internally
    """
    err = None

    def __init__(self, error, *args: object) -> None:
        super().__init__(*args)
        self.err = error

def solve_captcha(driver, iframe, t=5):
    """Solve the given captcha

#### Args:
    `driver` (`WebDriver`): The Selenium WebDriver instance
    `iframe` (`WebElement`): A reference to the captcha's iframe
    `t` (`int`, optional): Page load timeout (in seconds). Defaults to 5.

#### Returns:
        `Tuple(int, str)`: Error code (0 on success) and the answer (empty if error)
    """

    ret = None
    tmp_dir = tempfile.gettempdir()
    mp3_file = os.path.join(tmp_dir, "_tmp.mp3")
    wav_file = os.path.join(tmp_dir, "_tmp.wav")
    tmp_files = [mp3_file, wav_file]
    wait = WebDriverWait(driver, 20)  # Increase wait time

    try:
        print("Attempting to solve captcha...")
        
        # Wait for the reCAPTCHA iframe to be present
        print("Switching to reCAPTCHA iframe...")
        driver.switch_to.frame(iframe)
        print("Successfully switched to reCAPTCHA iframe")

        # Click the checkbox using JavaScript
        print("Looking for checkbox...")
        checkbox = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "recaptcha-checkbox-border")))
        print("Found checkbox, clicking with JavaScript...")
        driver.execute_script("arguments[0].click();", checkbox)
        time.sleep(3)  # Give more time for the checkbox animation
        print("Clicked checkbox")

        # Switch back to default content
        print("Switching back to default content...")
        driver.switch_to.default_content()
        print("Switched to default content")

        # Wait for and switch to the challenge iframe
        print("Looking for challenge iframe...")
        time.sleep(2)  # Wait for iframe to appear
        
        # Try different ways to find the challenge iframe
        challenge_frame = None
        try:
            # Try by title
            challenge_frame = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[title="recaptcha challenge"]')))
        except:
            try:
                # Try by name pattern
                challenge_frame = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'iframe[name^="c-"]')))
            except:
                try:
                    # Try finding all iframes and checking each one
                    iframes = driver.find_elements(By.TAG_NAME, "iframe")
                    for frame in iframes:
                        try:
                            if "challenge" in frame.get_attribute("title").lower():
                                challenge_frame = frame
                                break
                        except:
                            continue
                except:
                    pass
        
        if not challenge_frame:
            print("Challenge iframe not found")
            raise Exception("Challenge iframe not found")
            
        print("Found challenge iframe, switching...")
        wait.until(EC.visibility_of(challenge_frame))  # Wait for iframe to be visible
        driver.switch_to.frame(challenge_frame)
        print("Switched to challenge iframe")

        # Click audio button using JavaScript
        print("Looking for audio button...")
        audio_button = wait.until(EC.presence_of_element_located((By.ID, "recaptcha-audio-button")))
        print("Found audio button, clicking with JavaScript...")
        driver.execute_script("arguments[0].click();", audio_button)
        time.sleep(2)  # Give more time for audio challenge to load
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

        # Using google's own api against them
        print("Recognizing speech...")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_file) as source:
            recorded_audio = recognizer.listen(source)
            text = recognizer.recognize_google(recorded_audio)
        print(f"Recognized text: {text}")

        # Type out the answer
        print("Entering answer...")
        audio_response = wait.until(EC.presence_of_element_located((By.ID, "audio-response")))
        audio_response.send_keys(text)
        time.sleep(2)  # Give more time for text input
        print("Entered answer")

        # Click verify using JavaScript
        print("Looking for verify button...")
        verify_button = wait.until(EC.presence_of_element_located((By.ID, "recaptcha-verify-button")))
        print("Found verify button, clicking with JavaScript...")
        driver.execute_script("arguments[0].click();", verify_button)
        time.sleep(3)  # Give more time for verification
        print("Clicked verify button")

        ret = (status.SUCCESS, text)

    except TimeoutError as e:
        print(f"Timeout error: {e}")
        ret = (status.TIMEOUT, "")

    except NotExistent as e:
        print(f"Not existent error: {e}")
        ret = (e.err, "")

    except Exception as e:
        print(f"Unexpected error: {e}")
        ret = (status.UNKNOWN, "")

    finally:
        # Switch back to default content
        try:
            print("Switching back to default content...")
            driver.switch_to.default_content()
            print("Switched to default content")
        except Exception as e:
            print(f"Error switching to default content: {e}")
            
        print("Cleaning up temporary files...")
        __cleanup(tmp_files)
        print("Cleanup complete")
        return ret

def __cleanup(files: list):
    for x in files:
        if os.path.exists(x):
            os.remove(x)
