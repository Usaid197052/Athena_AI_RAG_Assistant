"""
Live wiring tests for RAG and vision tools through intent + planner.

Requires Ollama with qwen3.5:9b.

Run: python -m Tests.rag_vision_wiring_test
"""

from brain.intent_router import classify_intent
from brain.planner import create_plan


CASES = [
    ("ingest report.pdf", "action", "ingest_document"),
    ("what does the document say about pricing", "action", "query_documents"),
    ("which documents have you ingested", "action", "list_ingested_documents"),
    ("take a screenshot", "action", "take_screenshot"),
    ("read what is on my screen", "action", "read_screen"),
    ("click the Save button", "action", "click_text"),
    ("type hello world", "action", "type_text"),
    ("press enter", "action", "press_key"),
]


def run():

    failures = 0

    for request, expected_intent, expected_tool in CASES:

        intent = classify_intent(request)

        got_intent = intent.get("intent")

        plan = create_plan(request)

        tools = [
            step.get("tool")
            for step in plan.get("steps", [])
        ]

        ok = (
            got_intent == expected_intent
            and expected_tool in tools
            and not plan.get("error")
        )

        status = "PASS" if ok else "FAIL"

        if not ok:
            failures += 1

        print(
            f"{status}: '{request}' -> "
            f"intent={got_intent}, tools={tools}, "
            f"error={plan.get('error')}"
        )

    if failures:
        print(f"\n{failures} failure(s).")
        raise SystemExit(1)

    print("\nAll RAG/vision wiring tests passed.")


if __name__ == "__main__":
    run()
