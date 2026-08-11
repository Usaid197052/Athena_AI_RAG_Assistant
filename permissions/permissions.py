"""
Legacy permissions module.

Delegates to security.permissions while keeping the old DANGEROUS_TOOLS set
for tests that import it directly.
"""

from security.permissions import requires_confirmation as _requires
from security.risk import RiskLevel, classify_risk

DANGEROUS_TOOLS = {
    "shutdown_pc",
    "restart_pc",
    "sleep_pc",
    "delete_file",
    "send_email",
    "click_text",
    "type_text",
    "press_key",
}


def requires_confirmation(tool_name: str) -> bool:
    # Preserve explicit dangerous set + new risk engine
    if tool_name in DANGEROUS_TOOLS:
        return True
    decision_needed = _requires(tool_name)
    if classify_risk(tool_name) in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        return True
    return decision_needed
