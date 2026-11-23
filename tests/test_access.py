from uuid import uuid4

import pytest

from application.access import AccessError, Action, authorize_project


@pytest.mark.parametrize(("role", "allowed"), [
    ("viewer", {Action.READ}),
    ("operator", {Action.READ, Action.MANAGE_TARGETS, Action.REQUEST_AUTHORIZATION, Action.MANAGE_ASSESSMENTS}),
    ("approver", {Action.READ, Action.DECIDE_AUTHORIZATION}),
    ("project_admin", {Action.READ, Action.MANAGE_PROJECT}),
    ("unknown", set()),
])
@pytest.mark.parametrize("action", list(Action))
def test_project_role_controls_single_action(role, allowed, action):
    org, project, user = uuid4(), uuid4(), uuid4()
    membership = ("org_admin", role)
    if action in allowed:
        access = authorize_project(org, project, user, membership, action)
        assert access.permissions == allowed
        assert access.user_id == user
        return
    with pytest.raises(AccessError) as error:
        authorize_project(org, project, user, membership, action)
    assert error.value.status == 403


def test_project_without_membership_is_hidden():
    with pytest.raises(AccessError) as error:
        authorize_project(uuid4(), uuid4(), uuid4(), None, Action.READ)
    assert error.value.status == 404
