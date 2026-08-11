import pyautogui

from vision.screenshot import capture_screen
from vision.ocr import ocr_image
from logs.logger import write_log


# Moving the mouse to a screen corner aborts automation.
pyautogui.FAILSAFE = True


def find_on_screen(text: str, max_results: int = 8) -> str:
    """
    Locate on-screen text via OCR without clicking.
    Returns ranked matches with coordinates for richer targeting.
    """
    try:
        image_path = capture_screen()
        entries = ocr_image(image_path)
        target = str(text or "").lower().strip()
        if not target:
            return "Error: text to find is required."

        matches = []
        for found_text, x, y in entries:
            lowered = found_text.lower()
            if target in lowered:
                # Prefer closer / shorter labels first
                score = abs(len(lowered) - len(target))
                matches.append((score, found_text, int(x), int(y)))

        if not matches:
            return f"No on-screen matches for '{text}'."

        matches.sort(key=lambda item: item[0])
        limit = max(1, min(int(max_results or 8), 20))
        lines = [f"Found {len(matches)} match(es) for '{text}':"]
        for index, (_score, found_text, x, y) in enumerate(matches[:limit], start=1):
            lines.append(f"{index}. '{found_text}' at ({x}, {y})")
        return "\n".join(lines)
    except Exception as e:
        return f"Error finding on-screen text: {e}"


def click_text(text, match_index: int = 1):
    """
    Tool: finds text on screen using OCR and clicks it.

    match_index selects among multiple matches (1-based).
    """

    try:

        image_path = capture_screen()

        entries = ocr_image(image_path)

        target = str(text).lower().strip()
        hits = [
            (found_text, x, y)
            for found_text, x, y in entries
            if target in found_text.lower()
        ]
        # Prefer shorter OCR strings (closer to the label)
        hits.sort(key=lambda item: abs(len(item[0]) - len(target)))

        index = max(1, int(match_index or 1)) - 1
        if not hits:
            return f"Could not find '{text}' on screen."
        if index >= len(hits):
            return (
                f"Only found {len(hits)} match(es) for '{text}'. "
                f"Requested index {index + 1}."
            )

        found_text, x, y = hits[index]
        pyautogui.click(x, y)

        write_log(
            f"VISION: clicked '{found_text}' "
            f"at ({x}, {y}) index={index + 1}"
        )

        return (
            f"Clicked '{found_text}' at ({x}, {y}) "
            f"(match {index + 1}/{len(hits)})."
        )

    except Exception as e:

        return f"Error clicking text: {e}"


def click_at(x: int, y: int):
    """Click absolute screen coordinates (from find_on_screen)."""
    try:
        px, py = int(x), int(y)
        pyautogui.click(px, py)
        write_log(f"VISION: clicked coordinates ({px}, {py})")
        return f"Clicked at ({px}, {py})."
    except Exception as e:
        return f"Error clicking coordinates: {e}"


def type_text(text):
    """
    Tool: types text into the currently focused window.
    """

    try:

        pyautogui.typewrite(text, interval=0.03)

        write_log(f"VISION: typed text ({len(text)} chars)")

        return f"Typed: {text}"

    except Exception as e:

        return f"Error typing text: {e}"


def press_key(key):
    """
    Tool: presses a keyboard key (for example enter, tab, esc).
    """

    try:

        pyautogui.press(key)

        write_log(f"VISION: pressed key '{key}'")

        return f"Pressed {key}."

    except Exception as e:

        return f"Error pressing key: {e}"


def scroll_screen(clicks: int = -3):
    """
    Tool: scrolls the active window.
    Positive clicks scroll up; negative scroll down.
    """

    try:
        amount = int(clicks)
        pyautogui.scroll(amount)
        write_log(f"VISION: scrolled clicks={amount}")
        direction = "up" if amount > 0 else "down"
        return f"Scrolled {direction} ({amount})."
    except Exception as e:
        return f"Error scrolling: {e}"
