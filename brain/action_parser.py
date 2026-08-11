from brain.ollama_client import ask_athena
from brain.planner import extract_json
from tools.tool_registry import TOOLS


def parse_action(user_request):

    available_tools = "\n".join(TOOLS.keys())

    prompt = f"""
You are Athena, a desktop AI assistant.

Available tools:

{available_tools}

Tool argument guide:
- open_application: {{"application_name": "Visual Studio"}}
- close_application: {{"application_name": "Notepad"}}
- ingest_document: {{"file_path": "path.pdf"}}
- query_documents: {{"question": "..."}}
- list_ingested_documents: {{}}
- take_screenshot: {{}}
- read_screen: {{}}
- click_text: {{"text": "Save"}}
- type_text: {{"text": "hello"}}
- press_key: {{"key": "enter"}}

Your job is to convert the user's request into JSON.

Rules:
- Return ONLY valid JSON.
- No explanations.
- No markdown.
- No extra text.
- Always return a tool and arguments object.
- If no arguments are required, return an empty arguments object.
- Use only the tools listed above.
- Prefer open_application with a friendly name (never an executable path)
- Document questions -> query_documents
- Screen reading -> read_screen
- UI clicks -> click_text

Examples:

User:
Open Visual Studio

Response:
{{"tool":"open_application","arguments":{{"application_name":"Visual Studio"}}}}

User:
Open Notepad

Response:
{{"tool":"open_application","arguments":{{"application_name":"Notepad"}}}}

User:
Open Calculator

Response:
{{"tool":"open_application","arguments":{{"application_name":"Calculator"}}}}

User:
Open Command Prompt

Response:
{{"tool":"open_application","arguments":{{"application_name":"Command Prompt"}}}}

User:
Open PowerShell

Response:
{{"tool":"open_application","arguments":{{"application_name":"Windows PowerShell"}}}}

User:
Open Docker Desktop

Response:
{{"tool":"open_application","arguments":{{"application_name":"Docker Desktop"}}}}

User:
Close Notepad

Response:
{{"tool":"close_application","arguments":{{"application_name":"Notepad"}}}}

User:
Create a file called notes.txt

Response:
{{"tool":"create_file","arguments":{{"file_path":"notes.txt"}}}}

User:
Read notes.txt

Response:
{{"tool":"read_file","arguments":{{"file_path":"notes.txt"}}}}

User:
List files in D:\\Projects\\Jarvis

Response:
{{"tool":"list_files","arguments":{{"folder_path":"D:\\\\Projects\\\\Jarvis"}}}}

User:
Delete notes.txt

Response:
{{"tool":"delete_file","arguments":{{"file_path":"notes.txt"}}}}

User:
Rename hello.py to test.py

Response:
{{"tool":"rename_file","arguments":{{"old_name":"hello.py","new_name":"test.py"}}}}

User:
Move report.csv to D:\\Reports

Response:
{{"tool":"move_file","arguments":{{"source_path":"report.csv","destination_path":"D:\\\\Reports"}}}}

User:
Copy data.csv to backup.csv

Response:
{{"tool":"copy_file","arguments":{{"source_path":"data.csv","destination_path":"backup.csv"}}}}

User:
Run hello.py

Response:
{{"tool":"run_python_script","arguments":{{"script_path":"hello.py"}}}}

User:
Run ipconfig

Response:
{{"tool":"run_cmd_command","arguments":{{"command":"ipconfig"}}}}

User:
Get all running processes

Response:
{{"tool":"run_powershell_command","arguments":{{"command":"Get-Process"}}}}

User:
Shutdown my computer

Response:
{{"tool":"shutdown_pc","arguments":{{}}}}

User:
Restart my computer

Response:
{{"tool":"restart_pc","arguments":{{}}}}

User:
Put my computer to sleep

Response:
{{"tool":"sleep_pc","arguments":{{}}}}

User:
Ingest the document report.pdf

Response:
{{"tool":"ingest_document","arguments":{{"file_path":"report.pdf"}}}}

User:
What does the document say about pricing?

Response:
{{"tool":"query_documents","arguments":{{"question":"What does the document say about pricing?"}}}}

User:
Which documents have you read?

Response:
{{"tool":"list_ingested_documents","arguments":{{}}}}

User:
Take a screenshot

Response:
{{"tool":"take_screenshot","arguments":{{}}}}

User:
Read what is on my screen

Response:
{{"tool":"read_screen","arguments":{{}}}}

User:
Click the Save button

Response:
{{"tool":"click_text","arguments":{{"text":"Save"}}}}

User:
Type hello world

Response:
{{"tool":"type_text","arguments":{{"text":"hello world"}}}}

User:
Press enter

Response:
{{"tool":"press_key","arguments":{{"key":"enter"}}}}

User Request:
{user_request}
"""

    response = ask_athena(prompt)

    try:

        action = extract_json(response)

    except Exception as e:

        return {
            "tool": None,
            "arguments": {},
            "error": f"JSON Parse Error: {e}",
            "raw_response": response
        }

    tool = action.get("tool")

    if tool not in TOOLS:

        return {
            "tool": None,
            "arguments": {},
            "error": f"Unknown tool: {tool}",
            "raw_response": response
        }

    if not isinstance(action.get("arguments", {}), dict):
        action["arguments"] = {}

    return action