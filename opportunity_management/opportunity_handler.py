"""Legacy assignment handler wrapper.

All assignment logic lives in opportunity_management.opportunity_management.utils.assignment.
"""

from opportunity_management.opportunity_management.utils import assignment as assignment_v2


def on_opportunity_insert(doc, method):
    return assignment_v2.on_opportunity_insert(doc, method)


def on_opportunity_update(doc, method):
    return assignment_v2.on_opportunity_update(doc, method)


# Backwards-compatible no-op stubs

def create_assignments_and_notify(doc, is_new=False):
    return assignment_v2.process_assignments(doc, is_new=is_new)


def handle_assignee_changes(doc):
    return None
