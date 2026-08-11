from brain.action_parser import parse_action
from executor.action_executor import execute_action
from permissions.permissions import requires_confirmation

from logs.logger import (
    log_request,
    log_action,
    log_result
)


def main():

    print("Athena Permission Test")
    print("Type 'exit' to quit")

    while True:

        request = input("\nYou: ")

        if request.lower() == "exit":
            break

        log_request(request)

        action = parse_action(request)

        print("\nParsed Action:")
        print(action)

        if action.get("tool") is None:

            print("\nError:")
            print(action["error"])

            if "raw_response" in action:

                print("\nRaw Response:")
                print(action["raw_response"])

            continue

        tool_name = action["tool"]

        log_action(
            tool_name,
            action["arguments"]
        )

        if requires_confirmation(tool_name):

            approval = input(
                f"\nAthena wants to execute '{tool_name}'. Proceed? (Y/N): "
            )

            if approval.lower() != "y":

                print("\nAction cancelled.")

                log_result(
                    "Action cancelled by user."
                )

                continue

        result = execute_action(
            tool_name,
            action["arguments"]
        )

        print("\nResult:")
        print(result)

        log_result(result)


if __name__ == "__main__":
    main()