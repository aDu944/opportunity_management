"""
Emoji reactions in the WhatsApp team inbox.

frappe_whatsapp stores a reaction as its own `WhatsApp Message` row
(`content_type="reaction"`, `message` = the emoji — empty when it is removed,
`reply_to_message_id` = the wamid reacted to). The inbox does not show those
rows as thread items; instead every message ThreadItem carries a `reactions`
list built here:

    [{"emoji": "👍", "direction": "in" | "out", "by": <user id> | None,
      "by_name": <full name> | ""}]

At most one entry per side — the customer's latest reaction ("in") and the
business's latest ("out", `by` = the agent who sent it). A latest row with
an empty emoji means "removed", so that side has no entry.

`latest_reactions` is pure (no frappe at import time) so the bench-free
tests can load this file with a stubbed `frappe`; everything else queries.
"""

import re

import frappe

REACTION = "reaction"

_ROW_FIELDS = ["name", "creation", "type", "message", "reply_to_message_id", "custom_sent_by"]


def _emoji(raw) -> str:
    # `message` is an HTML Editor field; a reaction is one emoji, so dropping
    # tags is all the cleaning it needs.
    return re.sub(r"<[^>]+>", "", str(raw or "")).strip()


def latest_reactions(rows, names=None):
    """{target wamid: [entry, …]} from reaction rows (dicts), latest per side."""
    latest = {}
    ordered = sorted(rows or [], key=lambda r: (str(r.get("creation") or ""), str(r.get("name") or "")))
    for row in ordered:
        target = row.get("reply_to_message_id")
        if not target:
            continue
        side = "in" if row.get("type") == "Incoming" else "out"
        latest.setdefault(target, {})[side] = row

    out = {}
    for target, sides in latest.items():
        entries = []
        for side in ("in", "out"):
            row = sides.get(side)
            emoji = _emoji(row.get("message")) if row else ""
            if not emoji:
                continue
            by = (row.get("custom_sent_by") or None) if side == "out" else None
            entries.append(
                {
                    "emoji": emoji,
                    "direction": side,
                    "by": by,
                    "by_name": ((names or {}).get(by) or by or "") if by else "",
                }
            )
        out[target] = entries
    return out


def _rows(conversation, filters):
    base = {"custom_conversation": conversation, "content_type": REACTION}
    base.update(filters)
    return frappe.get_all(
        "WhatsApp Message",
        filters=base,
        fields=_ROW_FIELDS,
        order_by="creation asc",
        limit_page_length=0,
    )


def _with_names(rows):
    from opportunity_management.opportunity_management.whatsapp_serializers import _full_names

    return latest_reactions(rows, _full_names([r.get("custom_sent_by") for r in rows]))


def reactions_for(conversation, wamids):
    """{wamid: [entry, …]} for these target messages — one query."""
    wanted = sorted({w for w in (wamids or []) if w})
    if not conversation or not wanted:
        return {}
    return _with_names(_rows(conversation, {"reply_to_message_id": ["in", wanted]}))


def attach_reactions(items, conversation):
    """Fill `reactions` (and the legacy `reaction`) on a page of ThreadItems."""
    messages = [i for i in items if i.get("kind") == "message" and i.get("message_id")]
    found = reactions_for(conversation, [i["message_id"] for i in messages])
    for item in messages:
        set_item_reactions(item, found.get(item["message_id"], []))
    return items


def set_item_reactions(item, entries):
    item["reactions"] = list(entries or [])
    # Legacy singular key: it used to carry a reaction row's own emoji, and
    # older app builds still read it. It is now the customer's current
    # reaction on this message (else ours), "" when there is none.
    item["reaction"] = item["reactions"][0]["emoji"] if item["reactions"] else ""


def reaction_updates_since(conversation, after):
    """`[{message_id, reactions}]` for every target that got a reaction row
    created after `after` — even when the target itself is older."""
    if not after:
        return []
    changed = _rows(conversation, {"creation": [">", after]})
    targets = sorted({r["reply_to_message_id"] for r in changed if r.get("reply_to_message_id")})
    if not targets:
        return []
    found = reactions_for(conversation, targets)
    return [{"message_id": t, "reactions": found.get(t, [])} for t in targets]


def publish_reaction(conv, target):
    """Realtime `{event: "reaction", conversation, message_id, reactions}`."""
    from opportunity_management.opportunity_management.whatsapp_hooks import publish_inbox_event

    reactions = reactions_for(conv.name, [target]).get(target, [])
    publish_inbox_event("reaction", conv, extra={"message_id": target, "reactions": reactions})
    return reactions
