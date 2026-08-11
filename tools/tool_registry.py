"""
Legacy TOOLS dict used by planner / executor / tests.

Backed by the new ToolRegistry.
"""

from tools.registry import get_registry

TOOLS = get_registry().as_legacy_dict()
