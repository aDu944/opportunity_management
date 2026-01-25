# ToDo Notification Duplicate Email Fix

## Root Cause Identified ✅

You were absolutely right! The issue was **multiple ToDos being created**.

### What Was Happening:

When you assign an opportunity to 2 employees + yourself:

1. **Code creates 3 separate ToDos:**
   - ToDo 1: Employee 1 (`allocated_to` = employee1@example.com)
   - ToDo 2: Employee 2 (`allocated_to` = employee2@example.com)
   - ToDo 3: You (`allocated_to` = your@email.com, automatically added as assigner)

2. **Your Notification triggers on each ToDo creation:**
   - Notification fires when ToDo 1 is created → Email sent
   - Notification fires when ToDo 2 is created → Email sent
   - Notification fires when ToDo 3 is created → Email sent

3. **Result: 3 separate emails** with different combinations of recipients based on your Notification's recipient configuration.

---

## The Fix Applied

### Code Change in `assignment.py`:

Added `frappe.flags.in_import = True` before creating ToDos to **suppress Notification triggers**.

```python
def create_opportunity_todo(doc, user_id):
    """Create a ToDo for the given user linked to the Opportunity."""
    try:
        # Suppress notifications during ToDo creation to avoid duplicates
        # The assignment email is already being sent separately
        frappe.flags.in_import = True  # ← NEW LINE

        todo = frappe.get_doc({
            "doctype": "ToDo",
            ...
        })
        todo.insert(ignore_permissions=True)

        frappe.flags.in_import = False  # ← NEW LINE

        frappe.db.commit()
```

### What This Does:

✅ **Prevents Notification from triggering** during programmatic ToDo creation
✅ **Assignment emails still sent** via the `send_assignment_email()` function (line 154)
✅ **Reminder Notifications still work** for existing ToDos (triggers separately)
✅ **No duplicate emails** during initial assignment

---

## How Emails Work Now

### 1. Initial Assignment (When Opportunity is Assigned)

**Email sent by:** `assignment.py` → `send_assignment_email()` function
**Who receives:** All assigned engineers + you (the assigner)
**Email content:**
- Cyan/Turquoise header "New Opportunity Assigned"
- Opportunity details (customer, tender, items)
- "View Task" button
- Beautiful HTML formatting

**Number of emails:** 1 email per person (sent individually)

### 2. Reminder Emails (Daily/Periodic)

**Email sent by:** Your Notification doctype (configured in UI)
**Who receives:** Based on your Notification recipients configuration
**Trigger:** Whatever event/condition you set (e.g., daily check, date-based)
**Number of emails:** 1 email per trigger (to all recipients or individually, depending on your settings)

---

## After Deployment

Once you deploy this update:

1. **Assign a test opportunity** to yourself + brother + employee
2. **You should receive:**
   - 1 assignment email (from `assignment.py`)
   - NOT 3 emails anymore
3. **Reminder emails** will still work from your Notification

---

## Recommendation: Keep Using Your Notification

Now that the duplicate issue is fixed, you can keep using your Notification for:

✅ **Reminder emails** (7 days, 3 days, 1 day before closing)
✅ **Status updates** (opportunity won, lost, etc.)
✅ **Any custom triggers** you want to add

Just make sure it's **not triggering on "ToDo: After Insert"** event, or it will send duplicate emails again.

### Best Notification Setup:

**For Reminder Emails:**
- **Document Type:** Opportunity (not ToDo!)
- **Event:** "Days Before" or "Value Change" or "Method"
- **Condition:** Check closing date and reminder flags
- **Recipients:** ☑️ "Send To All Assignees"

**Example Condition for 3-day reminder:**
```python
from frappe.utils import date_diff, getdate, nowdate

closing_date = doc.get("expected_closing")
if not closing_date:
    return False

days_until = date_diff(closing_date, nowdate())
return days_until == 3 and not doc.get("custom_reminder_3_sent")
```

---

## Alternative: Re-enable Scheduled Task for Fancy Emails

If you prefer the color-coded reminder emails (red for critical, orange for important), you can:

1. **Re-enable** the scheduled task in `hooks.py` (uncomment the scheduler_events)
2. **Disable** your Notification to avoid duplicates
3. Scheduled task will send beautiful automated reminders at 7, 3, 1, 0 days

The scheduled task emails look like this:
- **7 days:** Orange header "Important Reminder"
- **3 days:** Orange header "Important Reminder"
- **1 day:** Coral/Salmon header "Urgent Reminder"
- **0 days:** Red header "🚨 CRITICAL ALERT 🚨"

---

## Current Status

✅ **Fix applied** - ToDo creation now suppresses Notifications
✅ **Pushed to GitHub** - Ready for deployment
⏳ **Awaiting deployment** - Deploy when ready
⏳ **Test after deploy** - Verify no duplicate emails during assignment

---

## Quick Test After Deployment

1. Create a new opportunity
2. Assign to: Yourself + Your Brother + 1 Employee
3. Save the opportunity
4. **Expected result:** Each person gets **exactly 1 email** (the cyan/turquoise "New Opportunity Assigned" email)
5. **Not expected:** Multiple emails with different recipient combinations

---

*The duplicate email issue is now fixed! Deploy when convenient.*
