from config import ASSISTANT_NAME
from core.orchestrator import Orchestrator
from logs.logger import configure_logging, log_result
from monitoring.service import start_monitors, stop_monitors
from monitoring.status_store import append_activity, set_ux_phase, write_status
from voice.speech_to_text import record_audio, transcribe_audio
from voice.text_to_speech import speak
from voice.wake_word import wait_for_wake_word


def is_exit_request(text):

    text = text.lower()

    explicit_phrases = [
        "shutdown athena",
        "close athena",
        "stop athena",
        "shutdown jarvis",
        "close jarvis",
        "stop jarvis",
        "shut yourself down",
        "go offline",
        "stop listening",
        "you can exit now"
    ]

    if any(
        phrase in text
        for phrase in explicit_phrases
    ):
        return True

    if (
        ("athena" in text or "jarvis" in text)
        and (
            "shutdown" in text
            or "shut down" in text
            or "exit" in text
            or "quit" in text
        )
    ):
        return True

    return False


def confirm_step(step):
    """
    Voice + keyboard confirmation for dangerous plan steps.
    """

    tool_name = step["tool"]

    description = step.get("description", tool_name)

    prompt_message = (
        f"I am about to {description}. Should I proceed?"
    )

    print(f"\n{prompt_message}")
    set_ux_phase("Waiting for confirmation...", description)

    speak(prompt_message)

    approval = input(
        f"Confirm '{tool_name}'? (Y/N): "
    )

    return approval.strip().lower() == "y"


def main():

    configure_logging()
    start_monitors()
    write_status(voice="listening", listening=True, paused=False)
    set_ux_phase("Ready", "Waiting for wake word")
    append_activity(f"{ASSISTANT_NAME} voice loop started", category="system")

    print(f"{ASSISTANT_NAME} Voice Assistant")

    print("Waiting for wake word...")

    wait_for_wake_word()

    print(f"\n{ASSISTANT_NAME} Activated")

    speak(f"{ASSISTANT_NAME} is online.")
    append_activity(f"{ASSISTANT_NAME} activated", category="voice")
    set_ux_phase("Listening...", f"{ASSISTANT_NAME} is online")

    orchestrator = Orchestrator(confirm_callback=confirm_step)

    try:
        while True:

            write_status(voice="listening", listening=True)
            set_ux_phase("Listening...")
            audio_file = record_audio()

            write_status(voice="thinking")
            set_ux_phase("Thinking...", "Transcribing speech")
            transcription = transcribe_audio(audio_file)

            print(f"\nYou said: {transcription}")

            if not transcription.strip():

                print("No speech detected.")

                continue

            normalized_text = transcription.lower().strip()

            if is_exit_request(normalized_text):

                shutdown_message = f"{ASSISTANT_NAME} shutting down."

                print(f"\n{shutdown_message}")

                speak(shutdown_message)

                log_result("Voice session terminated.")
                append_activity("Voice session terminated", category="system")

                break

            write_status(current_task=transcription[:200], voice="working")
            set_ux_phase("Working...", transcription[:120])
            append_activity(f"Heard: {transcription}", category="voice")

            result = orchestrator.handle_text(transcription)

            print(f"\nMode: {result.get('mode')}")

            if result.get("mode") == "action" and result.get("plan"):
                steps = result["plan"].get("steps") or []
                if steps:
                    print(f"Plan ({len(steps)} step(s)):")
                    for index, step in enumerate(steps, start=1):
                        print(
                            f"  {index}. "
                            f"{step.get('description', step.get('tool'))}"
                        )
                if result.get("outcome"):
                    print(f"\nResult:\n{result['outcome'].get('summary', '')}")

            response = result.get("response") or ""
            print(f"\n{ASSISTANT_NAME}: {response}")
            append_activity(response[:240], category="response")
            set_ux_phase("Speaking...", response[:120])
            write_status(voice="speaking", current_task=None)
            speak(response)
            set_ux_phase("Listening...", "Ready for next command")

    finally:
        stop_monitors()
        write_status(listening=False, voice="idle")
        set_ux_phase("Idle")


if __name__ == "__main__":
    main()
