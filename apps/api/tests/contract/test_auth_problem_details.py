"""Problem-details contracts for auth exceptions."""

from core.exceptions.auth import AuthorizationError


def test_authorization_problem_details_filter_internal_identifiers() -> None:
    problem = AuthorizationError(
        "Requires workspace write access",
        details={
            "allowed_roles": ["admin", "owner"],
            "membership_id": "membership-id",
            "membership_role": "member",
            "user_id": "user-id",
            "workspace_id": "workspace-id",
        },
    ).to_problem_details()

    assert problem["allowed_roles"] == ["admin", "owner"]
    assert "membership_id" not in problem
    assert "membership_role" not in problem
    assert "user_id" not in problem
    assert "workspace_id" not in problem
