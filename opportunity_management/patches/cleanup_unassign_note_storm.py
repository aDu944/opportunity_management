"""
Clear the "Returned to the unassigned queue by …" note storm.

The Desk thread header rebuilt its assignee Autocomplete on every realtime
`conversation` event, and the control fires `change` **asynchronously** — after
the synchronous guard that was meant to swallow it — with an empty value. The
client read that as an unassign; the server wrote a System note and published a
`conversation` event unconditionally; the event rebuilt the header again. The
loop left tens of thousands of identical notes on the busiest threads and made
`notes_count` meaningless.

Both ends are fixed (the client never unassigns on an empty value, and
`unassign()` is a no-op on an already-unassigned thread). This patch clears what
the loop already wrote and re-derives `notes_count` from what survives.

Idempotent by construction:

  * only conversations carrying **more than two** such notes are touched, so a
    genuine claim/release pair is left alone and a second run finds nothing;
  * `notes_count` is recomputed as a COUNT, not adjusted by a delta.
"""

import frappe

NOTE_PREFIX = "Returned to the unassigned queue by "
# Two hand-offs on one thread is ordinary; three is the loop.
STORM_THRESHOLD = 2
CHUNK_SIZE = 200


def execute():
    if not frappe.db.table_exists("WhatsApp Internal Note"):
        print("WhatsApp inbox: no WhatsApp Internal Note table — nothing to clean")
        return

    deleted = _delete_storm_notes()
    _recount_notes()
    frappe.db.commit()
    print(f"WhatsApp inbox: deleted {deleted} unassign-storm notes, recounted notes_count")


def _storm_conversations():
    """[(conversation, count)] for threads the loop hit."""
    # The wildcard lives in the *parameter*, so there is no literal `%` in the
    # SQL text and nothing here needs doubling.
    return frappe.db.sql(
        """
        SELECT conversation, COUNT(*) AS notes
        FROM `tabWhatsApp Internal Note`
        WHERE note_type = 'System'
          AND text LIKE %(prefix)s
          AND conversation IS NOT NULL
        GROUP BY conversation
        HAVING COUNT(*) > %(threshold)s
        """,
        {"prefix": NOTE_PREFIX + "%", "threshold": STORM_THRESHOLD},
        as_dict=True,
    )


def _delete_storm_notes() -> int:
    rows = _storm_conversations()
    if not rows:
        return 0
    names = [row["conversation"] for row in rows]
    deleted = sum(int(row["notes"] or 0) for row in rows)
    # Bulk delete in chunks: one conversation can carry ~10,000 of these, and a
    # single IN () over every affected thread is a needlessly large statement.
    for start in range(0, len(names), CHUNK_SIZE):
        chunk = names[start : start + CHUNK_SIZE]
        frappe.db.delete(
            "WhatsApp Internal Note",
            {
                "note_type": "System",
                "text": ("like", NOTE_PREFIX + "%"),
                "conversation": ("in", chunk),
            },
        )
    return deleted


def _recount_notes():
    """`notes_count` is a cached COUNT; after a bulk delete it is a lie."""
    frappe.db.sql(
        """
        UPDATE `tabWhatsApp Conversation` c
        SET c.notes_count = (
            SELECT COUNT(*) FROM `tabWhatsApp Internal Note` n
            WHERE n.conversation = c.name
        )
        """
    )
