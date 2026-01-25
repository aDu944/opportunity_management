# Client Script + Notification Conflict Fix

## Root Cause: Dual Assignment Systems

You have **TWO systems** creating ToDos:

1. **Client Script** (JavaScript) - Your working script shown above
   - Runs in browser after save
   - Sequential processing with delay
   - Checks for duplicates
   - Shows green alerts
   - Works well!

2. **Server-side hooks** (Python) - The `assignment.py` code
   - Runs on server during save
   - Also creates ToDos
   - Also sends emails
   - Conflicts with client script!

**Result:** Both systems run → Duplicate ToDos → Multiple Notification triggers → Duplicate emails

---

## Fix Applied: Disabled Server-Side Assignment

I've disabled the server-side Opportunity hooks in `hooks.py`:

```python
# DISABLED: Using client script for assignment instead to avoid duplicates
doc_events = {
    # "Opportunity": {
    #     "on_update": "...",
    #     "after_insert": "...",
    # },
    "Quotation": {
        "on_submit": "..."  # This stays enabled for auto-close
    }
}
```

**Now only your client script creates ToDos!**

---

## Remaining Issue: Notification Still Triggering

Your client script creates ToDos using:
```javascript
frappe.client.insert({ doctype: 'ToDo', ... })
```

If your **Notification is set to trigger on ToDo events**, it will still fire multiple times.

### Check Your Notification Settings:

Go to: **Setup → Email → Notification** → Open your notification

**Is it set like this?**
- **Document Type:** ToDo ← WRONG! This causes duplicates
- **Event:** After Insert / New

**If yes, that's the problem!**

---

## Solution: Change Notification to Trigger on Opportunity (Not ToDo)

### Option 1: Daily Reminder Based on Opportunity (Recommended)

**Settings:**
- **Document Type:** **Opportunity** (not ToDo!)
- **Event:** **Method** or **Custom**
- **Condition:**
```python
# Check if reminder should be sent based on closing date
from frappe.utils import date_diff, getdate, nowdate

closing_date = doc.get("expected_closing")
if not closing_date:
    return False

days_until = date_diff(closing_date, nowdate())

# Send reminder at 7, 3, 1, 0 days before closing
if days_until not in [7, 3, 1, 0]:
    return False

# Check if reminder already sent (to avoid daily spam)
if days_until == 7 and doc.get("custom_reminder_7_sent"):
    return False
if days_until == 3 and doc.get("custom_reminder_3_sent"):
    return False
if days_until == 1 and doc.get("custom_reminder_1_sent"):
    return False
if days_until == 0 and doc.get("custom_reminder_0_sent"):
    return False

return True
```

- **Recipients:** ☑️ **Send To All Assignees**
- **Subject:** `Reminder - Opportunity {{ doc.name }} Closing in {{ days }} days`
- **Enabled:** Yes

**How it works:**
- Checks Opportunity closing date daily
- Sends reminder at specific intervals (7, 3, 1, 0 days)
- Uses reminder flags to prevent duplicate reminders
- Sends ONE email to all assignees

---

### Option 2: Disable Notification (Use Client Script Alerts Only)

If you don't need email reminders:
- **Disable** the Notification completely
- Your client script already shows green alerts: "Assigned to: [name]"
- Users see assignments in their ToDo list
- No email spam

---

### Option 3: Server Script for Reminder Logic

Create a **Server Script** that runs on a schedule (not on ToDo creation):

1. Go to: **Setup → Automation → Server Script → New**
2. **Script Type:** Scheduler Event
3. **Event Frequency:** Daily
4. **Script:**

```python
import frappe
from frappe.utils import date_diff, getdate, nowdate, get_url

# Get all open opportunities with closing date
opportunities = frappe.get_all(
    "Opportunity",
    filters={
        "status": ["not in", ["Lost", "Closed", "Converted"]],
        "expected_closing": ["is", "set"]
    },
    fields=["name", "expected_closing", "party_name"]
)

for opp in opportunities:
    closing_date = getdate(opp.expected_closing)
    days_until = date_diff(closing_date, nowdate())

    # Only send at specific intervals
    if days_until not in [7, 3, 1, 0]:
        continue

    # Check if reminder already sent
    doc = frappe.get_doc("Opportunity", opp.name)
    reminder_field = f"custom_reminder_{days_until}_sent"

    if doc.get(reminder_field):
        continue  # Already sent

    # Get all assigned users from ToDos
    todos = frappe.get_all("ToDo",
        filters={
            "reference_type": "Opportunity",
            "reference_name": opp.name,
            "status": "Open"
        },
        fields=["allocated_to"]
    )

    recipients = list(set([t.allocated_to for t in todos if t.allocated_to]))

    if not recipients:
        continue

    # Send ONE email to all recipients
    frappe.sendmail(
        recipients=recipients,
        subject=f"Reminder - Opportunity {opp.name} Closing in {days_until} days",
        message=f"""
            <p>Your opportunity <strong>{opp.name}</strong> is closing in <strong>{days_until} days</strong>.</p>
            <p>Customer: {opp.party_name}</p>
            <p><a href="{get_url()}/app/opportunity/{opp.name}">View Opportunity</a></p>
        """,
        reference_doctype="Opportunity",
        reference_name=opp.name
    )

    # Mark reminder as sent
    frappe.db.set_value("Opportunity", opp.name, reminder_field, 1)
    frappe.db.commit()
```

This runs **once per day**, checks all opportunities, and sends **one email per opportunity** to all assignees.

---

## Recommended Configuration Summary

**For Assignment (Initial notification when assigned):**
- ✅ **Client Script** (your existing JS code)
- ✅ Shows green alerts in UI
- ✅ Creates ToDos sequentially
- ✅ No email needed (users see ToDo in their list)

**For Reminders (Periodic reminders before closing):**
- ✅ **Server Script** (scheduled daily) OR
- ✅ **Notification on Opportunity** (not ToDo!)
- ✅ Sends ONE email to all assignees
- ✅ Uses reminder flags to prevent duplicates

**What to DISABLE:**
- ❌ Server-side Opportunity hooks (already disabled in code)
- ❌ Notification on ToDo events (change to Opportunity or disable)
- ❌ Scheduled task in hooks.py (already disabled)

---

## After Deployment

1. **Deploy** the updated code (server-side hooks disabled)
2. **Check your Notification settings:**
   - If Document Type = "ToDo", change to "Opportunity" or disable
   - If Event = "After Insert" on ToDo, change to condition-based on Opportunity
3. **Test assignment:**
   - Assign opportunity to 3 people
   - Should see green alerts in UI
   - Each person should have 1 ToDo
   - NO emails sent (unless you set up reminder Notification/Server Script)

---

## Quick Decision Guide

**Do you want email reminders?**

**YES, I want reminders:**
→ Use **Option 3: Server Script** (most reliable, sends daily at specific intervals)

**NO, just UI alerts are fine:**
→ **Disable your Notification** completely
→ Users will see assignments in their ToDo list
→ Your client script already shows green alerts

**I want fancy reminder emails:**
→ Re-enable the **scheduled task** in hooks.py
→ Disable your Notification
→ You'll get beautiful color-coded emails (red/orange/cyan)

---

*The server-side assignment hooks are now disabled. Your client script will be the only system creating ToDos!*
