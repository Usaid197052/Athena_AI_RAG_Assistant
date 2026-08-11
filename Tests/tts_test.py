from voice.text_to_speech import speak


def main():

    print("Athena Text-To-Speech Test")
    print("Type 'exit' to quit.")

    while True:

        text = input("\nYou: ")

        if text.lower() == "exit":

            print("\nExiting TTS Test.")

            break

        speak(text)


if __name__ == "__main__":

    main()