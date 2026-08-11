import json
import re

from brain.ollama_client import ask_athena
from tools.tool_registry import TOOLS


def extract_json(text):
    """
    Extracts the first JSON object from an LLM response,
    tolerating <think> blocks and markdown fences.
    """

    text = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL
    )

    text = re.sub(r"```(?:json)?", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        raise ValueError("No JSON object found in response.")

    return json.loads(text[start:end + 1])


def validate_plan(plan):
    """
    Ensures the plan is well formed and only uses registered tools.
    Returns an error string, or None if the plan is valid.
    """

    steps = plan.get("steps")

    if not isinstance(steps, list) or not steps:
        return "Plan contains no steps."

    for index, step in enumerate(steps, start=1):

        if not isinstance(step, dict):
            return f"Step {index} is not an object."

        tool = step.get("tool")

        if tool not in TOOLS:
            return f"Step {index} uses unknown tool '{tool}'."

        if not isinstance(step.get("arguments", {}), dict):
            return f"Step {index} arguments must be an object."

    return None


def create_plan(user_request, extra_context: str = ""):
    """
    Decomposes a user request into an ordered list of tool steps.

    Returns:
    {
        "steps": [
            {
                "tool": "create_file",
                "arguments": {"file_path": "notes.txt"},
                "description": "Create notes.txt"
            }
        ]
    }

    On failure returns {"steps": [], "error": "...", "raw_response": "..."}.
    """

    from brain.prompt_manager import planner_preamble

    available_tools = "\n".join(TOOLS.keys())
    context_block = (
        f"\nUse this retrieved/session context when relevant "
        f"(especially project paths and preferences):\n{extra_context}\n"
        if extra_context.strip()
        else ""
    )

    prompt = f"""
{planner_preamble()}

Available tools:

{available_tools}

Tool argument guide (use these exact argument names):
- open_application: {{"application_name": "Visual Studio"}}
- close_application: {{"application_name": "Notepad"}}
- search_web: {{"query": "ClickHouse MergeTree"}}
- open_url: {{"url": "https://clickhouse.com/docs"}}
- list_workflows: {{}}
- mission_status: {{}}
- run_workflow: {{"workflow_name": "prepare_data_engineering_environment"}}
- check_docker / check_clickhouse / check_airflow / check_mysql / check_data_stack: {{}}
- list_containers: {{"all_containers": false}}
- clickhouse_tables: {{"database": "default"}}
- clickhouse_query: {{"sql": "SELECT 1"}}
- list_airflow_dags: {{"limit": 20}}
- airflow_dag_runs: {{"dag_id": "example_dag"}}
- analyze_csv: {{"file_path": "D:\\\\data\\\\sales.csv"}}
- draft_email: {{"to": "name@example.com", "subject": "Follow up", "body": "I'll follow up tomorrow."}}
- send_email: {{"draft_id": "..."}}
- list_email_drafts: {{}}
- scroll_screen: {{"clicks": -3}}
- ingest_document: {{"file_path": "path.pdf"}}
- query_documents: {{"question": "..."}}
- list_ingested_documents: {{}}
- take_screenshot: {{}}
- read_screen: {{}}
- click_text: {{"text": "Save"}}
- type_text: {{"text": "hello"}}
- press_key: {{"key": "enter"}}
- create_file / read_file / delete_file: {{"file_path": "..."}}
- list_files: {{"folder_path": "..."}}
- search_files: {{"folder_path": "...", "extension": "csv", "min_size_mb": 10}}
- get_file_info: {{"file_path": "..."}}
- get_system_status: {{}}
- list_processes: {{"limit": 15}}
- rename_file: {{"old_name": "...", "new_name": "..."}}
- move_file / copy_file: {{"source_path": "...", "destination_path": "..."}}
- run_python_script: {{"script_path": "..."}}
- run_cmd_command / run_powershell_command: {{"command": "..."}}
{context_block}
Routing rules for applications:
- Prefer open_application with a friendly name (never an .exe path)
- Prefer close_application to close apps by friendly name
- open_visual_studio / open_notepad / etc. are legacy aliases

Routing rules for documents and screen:
- Questions about uploaded/ingested documents -> query_documents
- Load a PDF/DOCX/TXT into memory -> ingest_document
- Capture the display -> take_screenshot
- Read visible on-screen text -> read_screen
- Click a label on screen -> click_text
- Type into the focused window -> type_text
- Press a key -> press_key

Your job is to decompose the user's request into an ordered list
of steps. Each step calls exactly one tool.

Rules:
- Return ONLY valid JSON.
- No explanations. No markdown. No extra text.
- Use only the tools listed above.
- Keep the plan as short as possible. A single step is fine.
- Each step has: "tool", "arguments", "description".
- If a step needs the output of a previous step, write the
  placeholder {{{{step_N}}}} inside the argument value, where N is
  the 1-based number of the earlier step.
- If the request cannot be done with the available tools,
  return {{"steps": []}}.

Examples:

User:
Open Notepad

Response:
{{"steps": [
  {{"tool": "open_application", "arguments": {{"application_name": "Notepad"}}, "description": "Open Notepad"}}
]}}

User:
Open Visual Studio

Response:
{{"steps": [
  {{"tool": "open_application", "arguments": {{"application_name": "Visual Studio"}}, "description": "Open Visual Studio"}}
]}}

User:
Open Docker Desktop

Response:
{{"steps": [
  {{"tool": "open_application", "arguments": {{"application_name": "Docker Desktop"}}, "description": "Open Docker Desktop"}}
]}}

User:
Close Notepad

Response:
{{"steps": [
  {{"tool": "close_application", "arguments": {{"application_name": "Notepad"}}, "description": "Close Notepad"}}
]}}

User:
Open my ClickHouse project

Response:
{{"steps": [
  {{"tool": "open_application", "arguments": {{"application_name": "Visual Studio"}}, "description": "Open preferred IDE from memory"}},
  {{"tool": "run_cmd_command", "arguments": {{"command": "explorer D:\\\\Projects\\\\Clickhouse-ETL-Pipeline"}}, "description": "Open project folder from memory"}}
]}}

User:
Check ClickHouse and Docker

Response:
{{"steps": [
  {{"tool": "check_data_stack", "arguments": {{}}, "description": "Check data engineering stack"}}
]}}

User:
Draft an email to Maryam saying I'll follow up tomorrow

Response:
{{"steps": [
  {{"tool": "draft_email", "arguments": {{"to": "maryam@example.com", "subject": "Follow up", "body": "Hi Maryam, I'll follow up tomorrow."}}, "description": "Draft follow-up email"}}
]}}

User:
Analyze sales.csv

Response:
{{"steps": [
  {{"tool": "analyze_csv", "arguments": {{"file_path": "sales.csv"}}, "description": "Profile sales.csv"}}
]}}

User:
Search the web for ClickHouse MergeTree

Response:
{{"steps": [
  {{"tool": "search_web", "arguments": {{"query": "ClickHouse MergeTree"}}, "description": "Search the web"}}
]}}

User:
What is my CPU usage?

Response:
{{"steps": [
  {{"tool": "get_system_status", "arguments": {{}}, "description": "Check system status"}}
]}}

User:
Find CSV files in Downloads

Response:
{{"steps": [
  {{"tool": "search_files", "arguments": {{"folder_path": "C:\\\\Users\\\\papab\\\\Downloads", "extension": "csv"}}, "description": "Search Downloads for CSV files"}}
]}}

User:
Create shopping.txt and then open Notepad

Response:
{{"steps": [
  {{"tool": "create_file", "arguments": {{"file_path": "shopping.txt"}}, "description": "Create shopping.txt"}},
  {{"tool": "open_application", "arguments": {{"application_name": "Notepad"}}, "description": "Open Notepad"}}
]}}

User:
Copy report.csv to D:\\Backup and then delete the original

Response:
{{"steps": [
  {{"tool": "copy_file", "arguments": {{"source_path": "report.csv", "destination_path": "D:\\\\Backup"}}, "description": "Copy report.csv to D:\\\\Backup"}},
  {{"tool": "delete_file", "arguments": {{"file_path": "report.csv"}}, "description": "Delete original report.csv"}}
]}}

User:
Read notes.txt and tell me what processes are running

Response:
{{"steps": [
  {{"tool": "read_file", "arguments": {{"file_path": "notes.txt"}}, "description": "Read notes.txt"}},
  {{"tool": "run_powershell_command", "arguments": {{"command": "Get-Process"}}, "description": "List running processes"}}
]}}

User:
Ingest the document report.pdf

Response:
{{"steps": [
  {{"tool": "ingest_document", "arguments": {{"file_path": "report.pdf"}}, "description": "Ingest report.pdf into document memory"}}
]}}

User:
What does the document say about pricing?

Response:
{{"steps": [
  {{"tool": "query_documents", "arguments": {{"question": "What does the document say about pricing?"}}, "description": "Search ingested documents for pricing"}}
]}}

User:
Ingest notes.txt and then ask what it says about deadlines

Response:
{{"steps": [
  {{"tool": "ingest_document", "arguments": {{"file_path": "notes.txt"}}, "description": "Ingest notes.txt"}},
  {{"tool": "query_documents", "arguments": {{"question": "What does it say about deadlines?"}}, "description": "Ask about deadlines in ingested documents"}}
]}}

User:
Which documents have you ingested?

Response:
{{"steps": [
  {{"tool": "list_ingested_documents", "arguments": {{}}, "description": "List ingested documents"}}
]}}

User:
Take a screenshot

Response:
{{"steps": [
  {{"tool": "take_screenshot", "arguments": {{}}, "description": "Capture the screen"}}
]}}

User:
Read what is on my screen

Response:
{{"steps": [
  {{"tool": "read_screen", "arguments": {{}}, "description": "OCR the current screen"}}
]}}

User:
Click the Save button

Response:
{{"steps": [
  {{"tool": "click_text", "arguments": {{"text": "Save"}}, "description": "Click Save on screen"}}
]}}

User:
Type hello world and press enter

Response:
{{"steps": [
  {{"tool": "type_text", "arguments": {{"text": "hello world"}}, "description": "Type hello world"}},
  {{"tool": "press_key", "arguments": {{"key": "enter"}}, "description": "Press enter"}}
]}}

User:
Take a screenshot and then read the screen

Response:
{{"steps": [
  {{"tool": "take_screenshot", "arguments": {{}}, "description": "Capture the screen"}},
  {{"tool": "read_screen", "arguments": {{}}, "description": "OCR the current screen"}}
]}}

User Request:
{user_request}
"""

    response = ask_athena(prompt)

    try:
        plan = extract_json(response)

    except Exception as e:

        return {
            "steps": [],
            "error": f"Plan Parse Error: {e}",
            "raw_response": response
        }

    error = validate_plan(plan)

    if error:

        return {
            "steps": [],
            "error": error,
            "raw_response": response
        }

    return plan
