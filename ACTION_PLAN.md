# Action Plan - Fix Duplicate Emails

## What We Fixed in the Code ✅

1. ✅ **Disabled server-side Opportunity assignment hooks**
   - No more duplicate ToDo creation
   - Your client script is now the only system creating ToDos

2. ✅ **Disabled scheduled reminder task**
   - Prevents duplicate reminder emails

3. ✅ **Added notification suppression flag in server code**
   - In case you re-enable server-side hooks later

4. ✅ **Fixed workspace to use shortcuts instead of cards**
   - Workspace now shows clickable links

---

## What You Need to Do in Frappe Cloud UI ⚡

### Step 1: Check Your Notification Settings (CRITICAL!)

1. Go to: **Setup → Email → Notification**
2. Find your Opportunity reminder notification
3. Check the **Document Type** field:

**If it says "ToDo":**
- ❌ **This is causing duplicate emails!**
- Change **Document Type** to: **"Opportunity"**
- Change **Event** to: **"Days Before"** or **"Custom"**
- OR just **disable** this notification

**If it says "Opportunity":**
- ✅ Good! Check that **Event** is not "After Save" (too frequent)
- Best Event: "Days Before" or condition-based

4. **Enable:** ☑️ **"Send To All Assignees"**
5. **Delete** the rows in Recipients table (allocated_to, assigned_by)
6. **Save**

---

### Step 2: Deploy Updated Code

1. **Deploy** the updated code to Frappe Cloud
2. **Wait for migration** to complete
3. **Refresh browser**

---

### Step 3: Test Assignment (After Deployment)

1. **Create a test opportunity**
2. **Assign to:** Yourself + Your Brother + 1 Employee
3. **Save**
4. **Expected result:**
   - You see 3 green alerts: "Assigned to: [name]"
   - 3 ToDos created (one per person)
   - **NO emails sent** during assignment (client script doesn't send emails)
   - Each person sees the ToDo in their ToDo list

---

## Email Configuration Options

Choose ONE of these options for emails:

### Option A: No Emails (Simplest)

**What:** Users only see ToDos in their list, no emails
**How:** Disable your Notification completely
**Pros:** ✅ No spam, ✅ No configuration needed
**Cons:** ❌ No email reminders

---

### Option B: Reminder Emails Only (Recommended)

**What:** Send email reminders at 7, 3, 1, 0 days before closing
**How:** Create a Server Script (see SERVER_SCRIPT_TEMPLATE.md)
**Pros:** ✅ One email per interval, ✅ Fully customizable
**Cons:** Requires creating a Server Script

**Quick Setup:**
1. Go to: **Setup → Automation → Server Script → New**
2. **Script Type:** Scheduler Event
3. **Event Frequency:** Daily
4. Paste the server script from CLIENT_SCRIPT_NOTIFICATION_FIX.md (Option 3)
5. Save and Enable

---

### Option C: Fancy Color-Coded Emails

**What:** Beautiful HTML emails with color coding (red=critical, orange=important)
**How:** Re-enable the scheduled task in code
**Pros:** ✅ Professional design, ✅ Color-coded urgency
**Cons:** Requires code change and redeployment

**To Enable:**
1. Tell me you want this option
2. I'll uncomment the scheduler_events in hooks.py
3. Deploy updated code
4. Emails sent automatically at 8 AM daily

---

## Current Status

✅ **Code Changes:** Complete and pushed to GitHub
⏳ **Deployment:** Ready to deploy
⏳ **Notification Fix:** You need to check/change in UI (Step 1 above)
⏳ **Testing:** After deployment

---

## Expected Behavior After Fix

### During Assignment:
1. You save Opportunity with 3 assignees
2. Client script creates 3 ToDos (sequential, with delays)
3. Green alerts show in UI: "Assigned to: [name]"
4. **NO emails sent** (client script doesn't send emails)
5. Each person sees ToDo in their list

### Reminder Emails:
- **If you choose Option A:** No emails ever
- **If you choose Option B:** One email per interval (7, 3, 1, 0 days) to all assignees
- **If you choose Option C:** Fancy color-coded emails per interval

---

## Summary of Changes

| What | Before | After |
|------|--------|-------|
| ToDo Creation | Client script + Server hooks = Duplicates | Client script only |
| Assignment Emails | Multiple per assignment | None (or configure separately) |
| Reminder Emails | Notification triggering on ToDo | Configure: Server Script or Notification on Opportunity |
| Workspace | Text only, no links | Clickable shortcuts |

---

## Quick Start Checklist

- [ ] Deploy updated code to Frappe Cloud
- [ ] Check Notification: Change Document Type from "ToDo" to "Opportunity" (or disable)
- [ ] Test: Assign opportunity to 3 people
- [ ] Verify: Each person has 1 ToDo, no duplicate emails
- [ ] Choose email option: A, B, or C (see above)
- [ ] Configure reminders if needed (Server Script or Notification)

---

**Which email option do you prefer? A, B, or C?**
