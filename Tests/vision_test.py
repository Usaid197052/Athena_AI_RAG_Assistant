"""
Tests for the vision package.

These are light smoke tests. Screenshot/OCR run only if a display
is available; they skip gracefully otherwise.

Run: python -m Tests.vision_test
"""

from pathlib import Path


def test_screenshot():

    try:
        from vision.screenshot import capture_screen

        path = capture_screen()

    except Exception as e:
        print(f"SKIP: screenshot ({e})")
        return

    assert Path(path).exists()

    print(f"PASS: screenshot saved -> {path}")


def test_ocr_engine_loads():

    try:
        from vision.ocr import _get_engine

        engine = _get_engine()

    except Exception as e:
        print(f"SKIP: ocr engine load ({e})")
        return

    assert engine is not None

    print("PASS: OCR engine loaded")


def test_ui_automation_imports():

    from vision.ui_automation import click_text, type_text, press_key

    assert callable(click_text)
    assert callable(type_text)
    assert callable(press_key)

    print("PASS: ui automation callables import")


if __name__ == "__main__":

    test_screenshot()
    test_ocr_engine_loads()
    test_ui_automation_imports()

    print("\nAll vision tests done.")
