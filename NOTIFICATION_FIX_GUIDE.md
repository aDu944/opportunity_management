# Fix Notification Duplicate Emails - Proper Configuration

## Current Problem

Your Notification is sending **3 separate emails** with different recipient combinations:
- Email 1: You + Brother (both managers)
- Email 2: You + Employee (assigned worker)
- Email 3: You only

**Root Cause:** Using multiple recipient rows in the Notification causes Frappe to send separate emails for each row.

---

## Solution 1: Enable "Send To All Assignees" (Recommended)

This is the **simplest and best** solution:

### Steps:

1. Go to: **Setup → Email → Notification**
2. Find your Opportunity reminder notification
3. Scroll to the **Recipients** section
4. **Check the box:** ☑️ **"Send To All Assignees"**
5. **Delete both rows** in the Recipients table (allocated_to and assigned_by)
6. **Save**

### What This Does:

✅ Sends **ONE email** to all users assigned to the Opportunity (via ToDo)
✅ No duplicate emails
✅ Everyone gets the same message
✅ No need to specify fields - automatically picks up all assignees

### Result:

When you assign opportunity to: You + Brother + Employee
- **ONE email sent** to all 3 people
- All recipients in the "To:" field
- No duplicates

---

## Solution 2: Keep Current Setup But Fix Recipients

If you want to keep the field-based recipients (not recommended), you need to understand the issue:

### Current Setup (Wrong):

| No. | Receiver By Document Field |
|-----|---------------------------|
| 1   | allocated_to              |
| 2   | assigned_by               |

**Problem:** Frappe sends **2 separate emails** (one per row), causing overlaps.

### Fixed Setup:

**Option A: Send only to assigned worker**
- Keep only Row 1: `allocated_to`
- Remove Row 2: `assigned_by`

**Option B: Send only to manager who assigned**
- Remove Row 1: `allocated_to`
- Keep only Row 2: `assigned_by`

But neither option sends to all 3 people properly!

---

## Solution 3: Use Custom Recipients List (If You Need Specific Logic)

If you want **different emails** to different groups (managers vs workers), create **2 separate Notifications**:

### Notification 1: For Assigned Employees
- **Name:** "Opportunity Reminder - Assigned Workers"
- **Recipients:**
  - ☑️ Send To All Assignees
- **Condition:** None (always send)
- **Subject:** Reminder - Opportunity {doc.name} Closing Soon
- **Message:** Template for workers

### Notification 2: For Managers (You + Brother)
- **Name:** "Opportunity Reminder - Managers"
- **Recipients:**
  - Receiver By Role: "Sales Manager" (or whatever your role is)
- **Condition:** Check if opportunity is assigned to team
- **Subject:** [Manager Alert] Opportunity {doc.name} Needs Attention
- **Message:** Template for managers with team overview

---

## Solution 4: Use Server Script for Complex Logic

If the built-in options don't work, you can create a Server Script that sends emails exactly how you want:

### Server Script Example:

1. Go to: **Setup → Automation → Server Script → New**
2. **Script Type:** Document Event
3. **DocType:** Opportunity
4. **Event:** After Save (or On Update)
5. **Code:**

```python
import frappe
from frappe.utils import get_url

# Only run if this is a reminder trigger (you define the logic)
# For example, check if closing date is soon
from frappe.utils import date_diff, getdate, nowdate

closing_date = doc.get("expected_closing")
if not closing_date:
    return

days_until_closing = date_diff(closing_date, nowdate())

# Only send reminder at specific intervals
if days_until_closing not in [7, 3, 1, 0]:
    return

# Get all assigned users from ToDo
todos = frappe.get_all("ToDo",
    filters={
        "reference_type": "Opportunity",
        "reference_name": doc.name,
        "status": "Open"
    },
    fields=["allocated_to"]
)

# Collect unique recipients
recipients = set()
for todo in todos:
    if todo.allocated_to:
        recipients.add(todo.allocated_to)

# Add assigned_by (manager) too
if doc.get("assigned_by"):
    recipients.add(doc.assigned_by)

if not recipients:
    return

# Send ONE email to all recipients
frappe.sendmail(
    recipients=list(recipients),
    subject=f"Reminder - Opportunity {doc.name} Closing in {days_until_closing} days",
    message=f"""
        <p>Dear Team,</p>

        <p>This is a reminder that Opportunity <strong>{doc.name}</strong>
           is closing in <strong>{days_until_closing} days</strong>.</p>

        <p><strong>Customer:</strong> {doc.party_name}<br>
           <strong>Closing Date:</strong> {closing_date}<br>
           <strong>Status:</strong> {doc.status}</p>

        <p><a href="{get_url()}/app/opportunity/{doc.name}">View Opportunity</a></p>

        <p>Best regards,<br>Sales Team</p>
    """,
    reference_doctype="Opportunity",
    reference_name=doc.name
)
```

---

## Recommended Solution Summary

**Best Option: Solution 1 - "Send To All Assignees"**

Why this is best:
✅ **Simplest** - Just check one box
✅ **No duplicates** - ONE email to all assignees
✅ **No code needed** - Works immediately in UI
✅ **Automatic** - Picks up all assigned users
✅ **No deployment** - Change takes effect immediately

### Quick Steps:

1. Open your Notification
2. Check: ☑️ "Send To All Assignees"
3. Delete both rows in Recipients table
4. Save
5. Test with a sample opportunity

---

## Testing Your Fix

After applying the fix:

1. **Create a test opportunity**
2. **Assign to:** Yourself + Brother + Employee (via ToDo or custom_resp_eng)
3. **Trigger the notification** (by saving or based on your event)
4. **Check emails:**
   - Should receive **exactly 1 email**
   - All 3 recipients in the "To:" field
   - No duplicates

---

## Understanding Your Current Screenshot

Your screenshot shows:
```
Recipients
[ ] Send To All Assignees

Recipients table:
Row 1: allocated_to
Row 2: assigned_by
```

**This setup sends 2 separate emails:**
- Email 1: To everyone in `allocated_to` field
- Email 2: To everyone in `assigned_by` field

If both fields have overlapping people, you get duplicates!

**The fix:** Enable "Send To All Assignees" and clear the table.

---

## Email Templates vs Notifications

**You asked: Should I use Email Templates instead?**

**Answer:** Email Templates are just the **message format**, not the sending mechanism.

- **Notification** = When & Who to send to
- **Email Template** = What the email looks like

You can use **both together**:
1. Create an Email Template with nice formatting
2. Reference it in your Notification's "Email Template" field
3. Notification still controls who gets it and when

**For your case:** Fix the Notification recipients first. Email Templates won't solve the duplicate issue.

---

*Try Solution 1 first - it should fix your duplicate email problem immediately without any deployment!*
