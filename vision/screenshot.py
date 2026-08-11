from datetime import datetime
from pathlib import Path

from PIL import ImageGrab

from logs.logger import write_log


CAPTURE_DIR = Path("vision/captures")


def capture_screen():
    """
    Captures the full screen and returns the saved image path.
    """

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    image_path = CAPTURE_DIR / f"screenshot_{timestamp}.png"

    image = ImageGrab.grab()

    image.save(image_path)

    write_log(f"VISION: screenshot saved to {image_path}")

    return str(image_path)


def take_screenshot():
    """
    Tool: takes a screenshot and reports where it was saved.
    """

    try:

        path = capture_screen()

        return f"Screenshot saved to {path}"

    except Exception as e:

        return f"Error taking screenshot: {e}"
