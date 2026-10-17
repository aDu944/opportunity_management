"""Server-side shim for the `whatsapp-inbox` Desk page.

Deliberately empty. The page is now only a card forwarding to the `/inbox`
web app (the three-pane Desk UI was retired). The inbox endpoints live in the
shared contract in
`opportunity_management.opportunity_management.whatsapp_api` (plan §1.7),
which mobile binds to as well. Adding a whitelisted method here would fork
that contract, so new endpoints belong in `whatsapp_api` (and its
`whatsapp_api_inbox` / `whatsapp_api_messages` / `whatsapp_api_crm`
implementation modules), not in this file.

Frappe still imports this module when the page loads, so it must exist.
"""
