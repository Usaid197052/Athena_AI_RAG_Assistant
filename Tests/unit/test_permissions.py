from security.permissions import evaluate_permission, requires_confirmation
from security.risk import RiskLevel, classify_risk
from tools.base import RiskLevel as ToolRisk


def test_open_application_is_low_risk():
    assert classify_risk("open_application") == RiskLevel.LOW
    decision = evaluate_permission("open_application")
    assert decision.allowed is True
    assert decision.requires_confirmation is False


def test_delete_file_is_high_risk():
    assert classify_risk("delete_file") == RiskLevel.HIGH
    assert requires_confirmation("delete_file") is True


def test_tool_risk_enum_aligns():
    assert ToolRisk.LOW.value == "LOW"
