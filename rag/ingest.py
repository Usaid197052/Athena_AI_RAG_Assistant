from pathlib import Path


CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


def extract_text(file_path):
    """
    Extracts plain text from a PDF, DOCX, TXT, or MD file.
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":

        from pypdf import PdfReader

        reader = PdfReader(str(path))

        return "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )

    if suffix == ".docx":

        import docx

        document = docx.Document(str(path))

        return "\n".join(
            paragraph.text
            for paragraph in document.paragraphs
        )

    if suffix in (".txt", ".md"):

        return path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

    raise ValueError(
        f"Unsupported file type: {suffix}. "
        "Supported: .pdf, .docx, .txt, .md"
    )


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    Splits text into overlapping chunks for embedding.
    """

    text = text.strip()

    if not text:
        return []

    chunks = []

    start = 0

    while start < len(text):

        end = start + chunk_size

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        start = end - overlap

    return chunks
