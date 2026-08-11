"""
Legacy app helpers.

Prefer tools.applications.launcher.open_application.
These wrappers remain for older call sites.
"""

from tools.applications.launcher import open_application


def open_visual_studio():
    return str(open_application("Visual Studio"))


def open_notepad():
    return str(open_application("Notepad"))


def open_calculator():
    return str(open_application("Calculator"))


def open_cmd():
    return str(open_application("Command Prompt"))


def open_powershell():
    return str(open_application("Windows PowerShell"))
