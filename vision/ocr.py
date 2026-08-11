from vision.screenshot import capture_screen
from logs.logger import write_log


_engine = None


def _get_engine():
    """
    Lazily loads the OCR engine (RapidOCR, offline ONNX models).
    """

    global _engine

    if _engine is None:

        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()

    return _engine


def ocr_image(image_path):
    """
    Runs OCR on an image. Returns a list of
    (text, center_x, center_y) entries.
    """

    engine = _get_engine()

    result, _ = engine(image_path)

    entries = []

    if not result:
        return entries

    for box, text, confidence in result:

        xs = [point[0] for point in box]
        ys = [point[1] for point in box]

        center_x = int(sum(xs) / len(xs))
        center_y = int(sum(ys) / len(ys))

        entries.append((text, center_x, center_y))

    return entries


def read_screen():
    """
    Tool: captures the screen and returns all visible text.
    """

    try:

        image_path = capture_screen()

        entries = ocr_image(image_path)

        if not entries:
            return "No readable text found on screen."

        text = "\n".join(entry[0] for entry in entries)

        write_log(
            f"VISION: OCR read {len(entries)} text regions"
        )

        return text

    except Exception as e:

        return f"Error reading screen: {e}"
