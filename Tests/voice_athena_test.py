"""
Enter-to-record Athena loop (no wake word). Useful for debugging.

Run from project root:
    python -m Tests.voice_athena_test
"""

from voice.speech_to_text import (
    record_audio,
    transcribe_audio
)

from voice.text_to_speech import (
    speak
)

from brain.intent_router import (
    classify_intent
)

from brain.chat import (
    chat_with_athena
)

from brain.planner import (
    create_plan
)

from executor.plan_executor import (
    execute_plan
)

from logs.logger import (
    log_request,
    log_result
)


EXIT_PHRASES = {
    "exit",
    "quit",
    "goodbye",
    "close athena",
    "stop athena",
    "shutdown athena",
    "close jarvis",
    "stop jarvis",
    "shutdown jarvis"
}


def is_exit_request(text):

    text = text.lower().strip()

    return any(
        phrase in text
        for phrase in EXIT_PHRASES
    )


def confirm_step(step):

    tool_name = step["tool"]

    description = step.get("description", tool_name)

    approval = input(
        f"\nAthena wants to {description} ({tool_name}). "
        f"Proceed? (Y/N): "
    )

    return approval.strip().lower() == "y"


def handle_action(transcription):

    plan = create_plan(transcription)

    if plan.get("error") or not plan.get("steps"):

        message = "I could not work out how to do that."

        print(f"\n{message}")

        speak(message)

        log_result(plan.get("error", "Empty plan"))

        return

    print(f"\nPlan ({len(plan['steps'])} step(s)):")

    for index, step in enumerate(plan["steps"], start=1):
        print(
            f"  {index}. {step.get('description', step['tool'])}"
        )

    outcome = execute_plan(
        plan,
        confirm_callback=confirm_step
    )

    print(f"\nResult:\n{outcome['summary']}")

    if outcome["completed"] and outcome["results"]:
        speak(str(outcome["results"][-1]))
    elif not outcome["completed"]:
        speak("I stopped before finishing that.")


def main():

    print("Athena Voice Assistant")
    print("Press ENTER and speak.")

    while True:

        input("\nPress ENTER to record...")

        audio_file = record_audio()

        transcription = transcribe_audio(audio_file)

        print(f"\nYou said: {transcription}")

        if not transcription.strip():

            print("No speech detected.")

            continue

        if is_exit_request(transcription.lower().strip()):

            shutdown_message = "Athena shutting down."

            print(f"\n{shutdown_message}")

            speak(shutdown_message)

            log_result("Voice session terminated.")

            break

        log_request(transcription)

        intent = classify_intent(transcription)

        print(f"\nIntent: {intent}")

        if intent["intent"] == "chat":

            response = chat_with_athena(transcription)

            print(f"\nAthena: {response}")

            speak(response)

            log_result(response)

            continue

        handle_action(transcription)


if __name__ == "__main__":
    main()
