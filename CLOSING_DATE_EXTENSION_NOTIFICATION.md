# Closing Date Extension Notification Setup Guide

## Overview

This notification automatically alerts all assigned team members when an opportunity's closing date is extended, giving them good news about additional time to prepare their quotations.

## What's Included in the Email

The closing date extension email includes:

### Key Features:
- ✅ **Green "Good News" theme** - Positive color scheme (#4caf50 green)
- ✅ **Date comparison** - Shows old date (strikethrough) and new date
- ✅ **Automatic calculation** - Displays additional days gained
- ✅ **Custom customer handling** - Correctly displays "General" customer names
- ✅ **Opportunity details** - Customer, tender no, tender title, status
- ✅ **Professional formatting** - Full HTML with MSO/Outlook compatibility
- ✅ **Responsive design** - Works on desktop and mobile

### Email Preview:

```
┌────────────────────────────────────────┐
│ 📅 Closing Date Extended               │ ← Green header
│ Opportunity ID: #OPP-2024-00123       │
├────────────────────────────────────────┤
│ Dear Team,                             │
│                                        │
│ Good news! The closing date has been   │
│ extended. You now have additional time.│
│                                        │
│ ┌──────────────────────────────────┐ │
│ │ 📅 Date Extended                 │ │ ← Green box
│ │                                  │ │
│ │ Previous Date:  25/01/2026       │ │ ← Strikethrough
│ │ New Date:       02/02/2026       │ │ ← Bold green
│ │ Additional Time: +8 days         │ │ ← Green highlight
│ └──────────────────────────────────┘ │
│                                        │
│ ┌──────────────────────────────────┐ │
│ │ Opportunity No. │ OPP-2024-00123 │ │
│ │ Customer        │ ABC Company     │ │
│ │ Tender No.      │ TND-2024-456   │ │
│ │ Tender Title    │ Supply Equip.  │ │
│ │ Status          │ Open            │ │
│ └──────────────────────────────────┘ │
│                                        │
│ Please take advantage of this extra    │
│ time to review your quotation.         │
│                                        │
│     [ View Opportunity ]  ← Green btn │
│                                        │
│ Best regards,                          │
│ ALKHORA for General Trading Ltd        │
└────────────────────────────────────────┘
```

---

## How to Set Up the Notification

### Step 1: Deploy Your Code

After deployment, the email template will be automatically available in your system.

```bash
# The template will be created at:
# Setup → Email → Email Template → "Opportunity Closing Date Extended"
```

---

### Step 2: Create the Notification (Optional)

**Note:** The app now sends this notification automatically on Opportunity update when the closing date is extended. You can keep the Email Template only, or still configure a Notification in the UI if you prefer.

1. Go to: **Setup → Email → Notification → New**

2. **Fill in the following fields:**

   **Basic Settings:**
   - **Name:** `Opportunity Closing Date Extended`
   - **Enabled:** ☑️ (checked)
   - **Document Type:** `Opportunity`
   - **Send Alert On:** `Value Change`

   **Condition Settings:**
   - **Condition (Important!):**
     ```python
     doc.expected_closing and doc.has_value_changed("expected_closing") and frappe.utils.date_diff(doc.expected_closing, doc.get_doc_before_save().expected_closing) > 0
     ```

   **This condition checks:**
   - Closing date exists
   - Closing date was changed
   - New date is AFTER the old date (extended, not shortened)

   **Recipients:**
   - **Send To All Assignees:** ☑️ (checked)
   - **Recipients table:** Leave empty (Send To All Assignees handles it)

   **Email Template:**
   - **Email Template:** Select `Opportunity Closing Date Extended`
   - **Subject:** (Leave blank - template has subject)

3. **Save** the notification

---

## How It Works

### Trigger Logic:

```
User edits Opportunity
    ↓
Changes Expected Closing date
    ↓
New date > Old date? (Extended?)
    ↓ Yes
Notification triggers
    ↓
Gets all assignees from custom_resp_eng
    ↓
Sends email to each assignee
```

### Example Scenarios:

**Scenario 1: Date Extended ✅**
- Old date: 25/01/2026
- New date: 02/02/2026
- Result: Email sent (date extended by 8 days)

**Scenario 2: Date Shortened ❌**
- Old date: 02/02/2026
- New date: 25/01/2026
- Result: No email (date moved earlier, not extended)

**Scenario 3: Date Unchanged ❌**
- Old date: 25/01/2026
- New date: 25/01/2026
- Result: No email (no change)

**Scenario 4: No Assignees ❌**
- Opportunity has no assignees in custom_resp_eng
- Result: No email (no recipients)

---

## Testing the Notification

### Test Steps:

1. **Create a test opportunity:**
   - Set closing date: 3 days from today
   - Assign to yourself and 1-2 other people
   - Save

2. **Extend the closing date:**
   - Edit the opportunity
   - Change closing date to: 10 days from today
   - Save

3. **Check emails:**
   - Each assignee should receive 1 email
   - Email should show:
     - Old date (strikethrough)
     - New date (bold green)
     - Additional days calculated correctly

4. **Try shortening the date (negative test):**
   - Edit the opportunity again
   - Change closing date to: 5 days from today (earlier than before)
   - Save
   - Result: **NO email should be sent** (date shortened, not extended)

---

## Advanced Configuration

### Option 1: Only Notify on Significant Extensions

If you only want to notify when the date is extended by 3 or more days:

**Change the condition to:**
```python
doc.expected_closing and doc.has_value_changed("expected_closing") and frappe.utils.date_diff(doc.expected_closing, doc.get_doc_before_save().expected_closing) >= 3
```

---

### Option 2: Include Additional Recipients

If you want to notify management in addition to assignees:

1. Keep **Send To All Assignees** checked
2. Add rows to **Recipients** table:
   - Email: `manager@example.com`
   - Condition: (leave blank)

---

### Option 3: Add Custom Message

If you want to include a reason for the extension:

1. Add a custom field to Opportunity: `custom_extension_reason` (Small Text)
2. Modify the email template to include:
   ```html
   {% if doc.custom_extension_reason %}
   <tr>
       <td style="padding: 0 0 20px 0;">
           <p style="color: #555; font-size: 14px; font-weight: 600;">Reason for Extension:</p>
           <p style="color: #444; font-size: 14px;">{{ doc.custom_extension_reason }}</p>
       </td>
   </tr>
   {% endif %}
   ```

---

## Troubleshooting

### Email Not Sending

**Problem:** No email is sent when I extend the closing date.

**Solutions:**
1. **Check notification is enabled:**
   - Go to: Setup → Email → Notification
   - Find "Opportunity Closing Date Extended"
   - Ensure "Enabled" is checked

2. **Check condition:**
   - Make sure new date is AFTER old date (not before)
   - Verify opportunity has assignees in custom_resp_eng

3. **Check email account:**
   - Go to: Setup → Email → Email Account
   - Ensure outgoing email is configured

4. **Check error logs:**
   - Go to: System → Error Log
   - Look for email-related errors

---

### Email Shows "N/A" for Dates

**Problem:** Email shows "N/A" instead of dates.

**Solution:**
- This happens if `get_doc_before_save()` returns None
- Usually happens on first save (no previous value)
- This is expected behavior - extension emails shouldn't send on first save

---

### Wrong Number of Days Calculated

**Problem:** Additional days calculation is wrong.

**Solution:**
- The calculation uses `date_diff(new_date, old_date)`
- This returns the number of days between dates
- Example: 25/01 to 02/02 = 8 days
- If calculation seems wrong, check date formats

---

### Assignees Not Receiving Emails

**Problem:** Some assignees are not receiving emails.

**Solutions:**
1. **Check assignees list:**
   - Open the opportunity
   - Check custom_resp_eng table has all assignees
   - Verify each Responsible Engineer has a valid user/email

2. **Check user emails:**
   - Go to: Users → User List
   - Find each assignee
   - Ensure "Send Welcome Email" is enabled
   - Ensure email address is valid

3. **Check notification recipients:**
   - Ensure "Send To All Assignees" is checked
   - Or manually add users to Recipients table

---

## Email Template Features

### 1. Custom Customer Handling

The template intelligently handles "General" customers:

```jinja
{% set customer_display = doc.custom_man_customer_name if (doc.party_name == "General - عامة (USD)" or doc.party_name == "General - عامة (IQD)") and doc.custom_man_customer_name else doc.party_name %}
```

If customer is "General", it shows the manually entered customer name instead.

---

### 2. Date Comparison

Shows old vs new date with visual indication:

```jinja
{% set old_date = doc.get_doc_before_save().expected_closing if doc.get_doc_before_save() else None %}
{% set new_date = doc.expected_closing %}
```

Old date has strikethrough styling, new date is bold and green.

---

### 3. Automatic Days Calculation

Calculates and displays additional days:

```jinja
{% if old_date and new_date %}
{% set days_extended = frappe.utils.date_diff(new_date, old_date) %}
Additional Time: +{{ days_extended }} day{{ "s" if days_extended != 1 else "" }}
{% endif %}
```

Automatically handles singular vs plural ("day" vs "days").

---

### 4. Microsoft Outlook Compatibility

Includes VML code for Outlook:

```html
<!--[if mso]>
<v:roundrect ... fillcolor="#4caf50">
<![endif]-->
```

Ensures buttons and styling work correctly in Outlook.

---

## Summary

✅ **Created:** Closing date extension email template
✅ **Color:** Green (#4caf50) for positive news
✅ **Shows:** Old date, new date, additional days
✅ **Triggers:** Only when date is extended (moved forward)
✅ **Recipients:** All assignees automatically
✅ **Setup:** Simple notification configuration in UI

**Next Steps:**
1. Deploy your code to Frappe Cloud
2. Create the notification (Step 2 above)
3. Test with a sample opportunity
4. Enjoy automatic notifications! 🎉

---

## Related Documents

- **ACTION_PLAN.md** - Overall project setup and deployment
- **NOTIFICATION_DUPLICATE_ANALYSIS.md** - Understanding notification system
- **EMAIL_SAMPLES_COMPARISON.md** - Compare different email styles

**Questions?** Check the troubleshooting section or review your notification configuration!
