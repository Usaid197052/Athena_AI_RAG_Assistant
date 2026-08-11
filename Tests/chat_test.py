from brain.chat import chat_with_athena


while True:

    request = input("\nYou: ")

    if request.lower() == "exit":
        break

    response = chat_with_athena(
        request
    )

    print(
        f"\nAthena: {response}"
    )
