from brain.ollama_client import ask_athena
from brain.planner import extract_json


def classify_intent(user_request):

    prompt = f"""
You are an intent classifier.

Your task is to classify a user request.

Possible intents:

1. action
   - Open applications
   - Create, read, delete, move, or copy files
   - Run scripts or shell commands
   - Perform system actions (shutdown, restart, sleep)
   - Ingest or search documents (PDF, DOCX, TXT)
   - Ask questions about ingested documents
   - Take screenshots or read text on screen
   - Click on-screen UI, type text, or press keys

2. chat
   - General conversation
   - Explanations that do not need tools
   - Math questions with no computer action
   - World knowledge questions not based on local documents

Return ONLY JSON.

Examples:

User:
Open Notepad

Response:
{{"intent":"action"}}

User:
Create a file called notes.txt

Response:
{{"intent":"action"}}

User:
Ingest report.pdf

Response:
{{"intent":"action"}}

User:
What does the document say about pricing?

Response:
{{"intent":"action"}}

User:
Take a screenshot

Response:
{{"intent":"action"}}

User:
Read what is on my screen

Response:
{{"intent":"action"}}

User:
Click the Save button

Response:
{{"intent":"action"}}

User:
What is 1 + 1?

Response:
{{"intent":"chat"}}

User:
Who created Python?

Response:
{{"intent":"chat"}}

User:
Tell me a joke

Response:
{{"intent":"chat"}}

User Request:
{user_request}
"""

    response = ask_athena(prompt)

    try:

        result = extract_json(response)

        if result.get("intent") not in ("action", "chat"):
            return {"intent": "chat"}

        return result

    except Exception:

        return {
            "intent": "chat"
        }