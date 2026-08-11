from brain.tool_selector import select_tool
from executor.action_executor import execute_action


def main():

    print("Athena Agent Online")
    print("Type 'exit' to quit")

    while True:

        request = input("\nYou: ")

        if request.lower() == "exit":
            break

        selected_tool = select_tool(request)

        print(f"\nSelected Tool: {selected_tool}")

        result = execute_action(selected_tool)

        print(f"Athena: {result}")


if __name__ == "__main__":
    main()