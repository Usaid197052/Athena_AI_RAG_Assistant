"""
Test Athena wake word detection.

Uses custom ONNX if voice/models/hey_athena.onnx exists,
otherwise Whisper STT listening for 'Hey Athena'.

Run: python -m Tests.wakeword_test
"""

from voice.wake_word import wait_for_wake_word


print("Athena wake word test")
print("Say: 'Hey Athena'")

wait_for_wake_word()

print("Wake word accepted. Test complete.")
