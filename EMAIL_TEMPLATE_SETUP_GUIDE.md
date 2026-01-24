# Email Template Setup Guide - Enhanced Simple Emails

## Overview

This guide shows you how to use the enhanced email templates for Opportunity notifications. These templates provide **much more information** than standard Frappe notifications while being simpler than the fully color-coded scheduled task emails.

## What's Included in the Templates

Both email templates now include:

### Opportunity Assignment Template
- ✅ Opportunity number with clickable link
- ✅ Customer name
- ✅ Opportunity type
- ✅ Tender number (if set)
- ✅ Tender title
- ✅ Expected closing date (highlighted in red)
- ✅ Status
- ✅ Assigned by (person's name)
- ✅ **Full items table** with Item Code, Item Name, Qty, UOM
- ✅ Action button to view opportunity
- ✅ Professional formatting with tables
- ✅ Company signature (ALKHORA for General Trading Ltd)

### Opportunity Reminder Template
- ✅ All the above details PLUS:
- ✅ **Smart urgency alerts** that change based on days remaining:
  - 🚨 Red "CRITICAL" alert if closing today
  - ⏰ Orange "URGENT" alert if closing tomorrow
  - ⏰ Yellow "IMPORTANT" alert if closing in 3-7 days
- ✅ Days remaining calculation in the closing date field
- ✅ Dynamic action button (red for urgent, orange for normal)
- ✅ Items table with professional styling

---

## How to Set Up

### Step 1: Deploy Your Code

The email templates are included in the code. After deployment, Frappe will automatically create them in your system.

```bash
# After deploying to Frappe Cloud, the templates will be available at:
# Setup → Email → Email Template
```

---

### Step 2: Option A - For Assignment Emails (When Someone is Assigned)

**If you want assignment emails:**

1. Go to: **Setup → Email → Notification → New**
2. Fill in:
   - **Name:** Opportunity Assignment Notification
   - **Document Type:** Opportunity
   - **Event:** After Save
   - **Condition:** `doc.custom_resp_eng and len(doc.custom_resp_eng) > 0`
   - **Send To:** ☑️ Send To All Assignees
   - **Subject:** Leave blank (template has subject)
   - **Email Template:** Select **"Opportunity Assignment"**

3. **Save and Enable**

**Note:** Your client script already creates ToDos when assigning. This notification is OPTIONAL - only enable if you want assignment emails in addition to the ToDos.

---

### Step 2: Option B - For Reminder Emails (Days Before Closing)

**Set up reminder notifications:**

1. Go to: **Setup → Email → Notification → New**
2. Fill in:
   - **Name:** Opportunity Reminder - 7 Days
   - **Document Type:** Opportunity
   - **Event:** Days Before (value: 7)
   - **Days Before or After:** Before
   - **Date Changed:** Expected Closing
   - **Condition:** `doc.status not in ["Lost", "Closed", "Converted"]`
   - **Send To:** ☑️ Send To All Assignees
   - **Email Template:** Select **"Opportunity Reminder"**

3. **Save and Enable**

4. **Repeat for 3 days, 1 day, and 0 days**:
   - Create separate notifications for each interval
   - Change the "Days Before" value (7, 3, 1, 0)
   - Use the same template "Opportunity Reminder" (it automatically adjusts urgency)

---

## Email Template Features

### Assignment Email Preview:

```
┌────────────────────────────────────────┐
│ New Opportunity Assigned               │
├────────────────────────────────────────┤
│ Dear Ahmed,                            │
│                                        │
│ A new opportunity has been assigned... │
│                                        │
│ ┌──────────────────────────────────┐ │
│ │ Opportunity No. │ OPP-2024-00123 │ │
│ │ Customer        │ ABC Company     │ │
│ │ Tender No.      │ TND-2024-456   │ │
│ │ Tender Title    │ Supply Equip.  │ │
│ │ Expected Close  │ 25/01/2026     │ │ ← Red color
│ │ Status          │ Open            │ │
│ │ Assigned By     │ Ali Ahmed       │ │
│ └──────────────────────────────────┘ │
│                                        │
│ Items to be Quoted:                    │
│ ┌──────────────────────────────────┐ │
│ │ Code │ Name  │ Qty │ UOM │       │ │
│ │ PUMP │ Pump  │  5  │ Pcs │       │ │
│ │ VALVE│ Valve │ 10  │ Pcs │       │ │
│ └──────────────────────────────────┘ │
│                                        │
│ [ View Opportunity ]  ← Blue button   │
│                                        │
│ Best regards,                          │
│ ALKHORA for General Trading Ltd        │
└────────────────────────────────────────┘
```

### Reminder Email (7 Days):

```
┌────────────────────────────────────────┐
│ Opportunity Reminder                   │
├────────────────────────────────────────┤
│ Dear Team,                             │
│                                        │
│ ⏰ Reminder: Closing in 7 days        │ ← Yellow alert
│                                        │
│ [Details table - same as above]       │
│ [Items table - same as above]         │
│                                        │
│ [ View Opportunity ]  ← Orange button │
└────────────────────────────────────────┘
```

### Reminder Email (1 Day - URGENT):

```
┌────────────────────────────────────────┐
│ Opportunity Reminder                   │
├────────────────────────────────────────┤
│ Dear Team,                             │
│                                        │
│ ⏰ URGENT: Closing TOMORROW!          │ ← Orange alert
│                                        │
│ Expected Closing: 25/01/2026           │
│                   - TOMORROW!          │ ← Red highlight
│                                        │
│ [ Take Action Now ]  ← Red button     │
└────────────────────────────────────────┘
```

### Reminder Email (0 Days - CRITICAL):

```
┌────────────────────────────────────────┐
│ Opportunity Reminder                   │
├────────────────────────────────────────┤
│ Dear Team,                             │
│                                        │
│ 🚨 CRITICAL: Closing TODAY!           │ ← Red alert
│                                        │
│ Expected Closing: 25/01/2026           │
│                   - TODAY!             │ ← Bold red
│                                        │
│ [ Take Action Now ]  ← Red button     │
└────────────────────────────────────────┘
```

---

## Comparison: Simple Templates vs Fancy Scheduled Emails

| Feature | Simple Templates (This Guide) | Fancy Scheduled Emails |
|---------|------------------------------|------------------------|
| **Setup** | Configure in UI (Notifications) | Already enabled (tasks.py) |
| **Design** | Clean tables, basic colors | Full color-coded design |
| **Information** | ✅ All details + items table | ✅ All details + items table |
| **Urgency Indicators** | ✅ Text + simple colors | ✅ Full color scheme per urgency |
| **Configuration** | Flexible (set any day interval) | Fixed (7, 3, 1, 0 days) |
| **Trigger** | Notification system | Daily cron job (8 AM) |
| **Customization** | Edit in UI | Edit Python code |
| **Email Time** | Event-based (immediate) | Daily at 8 AM |

---

## Which Option Should You Use?

### Use Simple Email Templates (This Guide) if:
- ✅ You want to configure reminder days in the UI (e.g., 10, 5, 2 days)
- ✅ You want emails sent immediately when conditions are met
- ✅ You prefer managing emails through Frappe's Notification UI
- ✅ You want a clean, professional look without too much color

### Use Fancy Scheduled Emails (Already Enabled) if:
- ✅ You want maximum visual impact with color-coded urgency
- ✅ 7, 3, 1, 0 day intervals work for you (no customization needed)
- ✅ Daily 8 AM email timing is acceptable
- ✅ You want the most professional, eye-catching design

---

## You Can Use BOTH!

**Recommended Configuration:**
- ✅ **Disable fancy scheduled emails** (comment out scheduler in hooks.py)
- ✅ **Use Simple Templates** for full control via Notifications

OR

- ✅ **Keep fancy scheduled emails enabled** (default)
- ✅ **Add Simple Assignment Template** for instant assignment notifications
- ✅ **Don't create reminder notifications** (fancy emails handle reminders)

---

## Testing Your Email Templates

### Test Assignment Email:
1. Create a test opportunity
2. Assign it to someone
3. Check their email inbox
4. Verify all fields appear correctly

### Test Reminder Email:
1. Create a test opportunity with closing date = 3 days from today
2. Go to: **Setup → Email → Notification**
3. Open your reminder notification
4. Click **"Send Test Email"**
5. Enter your email address
6. Check your inbox

---

## Troubleshooting

### Template doesn't show all fields:
- Some fields like `custom_tender_no` are optional
- The template uses `{% if doc.field %}` to show only available data
- This is normal - blank fields are hidden automatically

### No items table appearing:
- Check that your Opportunity has items in the `items` child table
- If no items, the table is automatically hidden

### Emails not sending:
1. Check: **Setup → Email → Email Account** (configured?)
2. Check: **Setup → Email → Notification** (enabled?)
3. Check notification conditions are met
4. Check **Error Log** for email errors

---

## Summary

✅ **Created:** 2 email templates with full opportunity details
✅ **Includes:** Customer, tender info, items table, urgency alerts
✅ **Setup:** Configure in Frappe Notification UI
✅ **Flexible:** Use for any day interval you want
✅ **Professional:** Clean, readable design with smart urgency

**Next Steps:**
1. Deploy your code to Frappe Cloud
2. Go to Setup → Email → Notification
3. Create notifications using the templates above
4. Test with a sample opportunity

**Questions?** Check the ACTION_PLAN.md for overall project context!
