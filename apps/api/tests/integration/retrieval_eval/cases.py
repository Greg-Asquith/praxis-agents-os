"""Data cases for the Gate G4 retrieval scoreboard."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalCase:
    """One query and its required document containment threshold."""

    query: str
    expect_doc: str
    within_top: int


CASES = (
    RetrievalCase("how do I connect to the vpn", "vpn_setup.md", 3),
    RetrievalCase("WireGuard configuration", "vpn_setup.md", 1),
    RetrievalCase("EXP-REIMBURSE-90", "travel_expense_policy.md", 1),
    RetrievalCase(
        "what is the daily food allowance when travelling",
        "travel_expense_policy.md",
        3,
    ),
    RetrievalCase(
        "who do I page when production is down",
        "security_incident_runbook.md",
        3,
    ),
    RetrievalCase("error 4032 meaning", "api_error_codes.md", 3),
    RetrievalCase("new starter first week tasks", "onboarding_guide.md", 3),
    RetrievalCase("volume discount tiers", "pricing_policy.md", 3),
)
