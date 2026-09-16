"""Server-side shim for the `whatsapp-inbox` Desk page.

Deliberately empty. Unlike `page/employee_team_assignment/`, this page owns
no endpoints of its own: every call the bundle makes goes to the shared
inbox contract in
`opportunity_management.opportunity_management.whatsapp_api` (plan §1.7),
which mobile binds to as well. Adding a whitelisted method here would fork
that contract, so new endpoints belong in `whatsapp_api` (and its
`whatsapp_api_inbox` / `whatsapp_api_messages` / `whatsapp_api_crm`
implementation modules), not in this file.

Frappe still imports this module when the page loads, so it must exist.
"""
