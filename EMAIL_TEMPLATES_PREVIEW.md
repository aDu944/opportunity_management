# Email Notification Templates - Preview

## Current Email Notification

The auto-close functionality sends **one email notification** when a Quotation is submitted.

---

## Email #1: Task Completed Notification

**Sent to:** All users assigned to the Opportunity (via ToDo)
**Sent when:** Quotation is submitted
**Current implementation:** Uses the existing notification system in `quotation_handler.py`

### Email Preview:

```
Subject: Task Completed: Opportunity OPP-2024-00123

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Your task has been completed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The Opportunity OPP-2024-00123 has been converted to a Quotation.

Quotation: QTN-2024-00456

┌─────────────────────────┐
│   View Quotation   │  ← Green button with link
└─────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### HTML Email Body:

```html
<h3>Your task has been completed</h3>

<p>The Opportunity <b>OPP-2024-00123</b> has been converted to a Quotation.</p>

<p><b>Quotation:</b> QTN-2024-00456</p>

<p>
    <a href="https://yoursite.com/app/quotation/QTN-2024-00456"
       style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
        View Quotation
    </a>
</p>
```

---

## Integration with Your Existing Notifications

### Question: Are you using the existing Notification system?

Looking at your screenshot, I can see you have **4 notification configurations**:

1. **New Opportunity Assigned** - Enabled, sends on New
2. **CRITICAL ALERT - Opportunity** - Enabled, Days Before
3. **Reminder - Opportunity** - Enabled, Days Before
4. **Urgent Reminder - Opportunity** - Enabled, Days Before

**Good news:** The auto-close notification is **separate** and **complementary** to your existing notifications. It doesn't interfere with them.

### How They Work Together:

```
Timeline of Notifications:
───────────────────────────────────────────────────────────

Day 1: Opportunity Created
  → Your notification: "New Opportunity Assigned" ✓

Day 5: 7 days before closing
  → Your notification: "Reminder - Opportunity" ✓

Day 7: 3 days before closing
  → Your notification: "CRITICAL ALERT" ✓

Day 9: 1 day before closing
  → Your notification: "Urgent Reminder" ✓

Day 10: Quotation Submitted
  → NEW auto-close notification: "Task Completed" ✓
  → Opportunity status → Converted ✓
  → ToDos closed ✓
```

---

## Enhanced Email Template (Optional Upgrade)

Would you like a more detailed email that matches your existing notification style? Here's an enhanced version:

### Enhanced Template Preview:

```
Subject: ✅ Task Completed: Opportunity OPP-2024-00123

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎉 Opportunity Converted to Quotation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Hi [User Name],

Good news! The opportunity you were working on has been successfully
converted to a quotation.

┌─────────────────────────────────────────────┐
│ Opportunity Details                         │
├─────────────────────────────────────────────┤
│ Opportunity: OPP-2024-00123                 │
│ Customer: ABC Company Ltd                   │
│ Amount: $50,000.00                          │
│ Status: Converted ✓                         │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ Quotation Created                           │
├─────────────────────────────────────────────┤
│ Quotation: QTN-2024-00456                   │
│ Date: January 21, 2026                      │
│ Status: Submitted ✓                         │
└─────────────────────────────────────────────┘

Your assigned tasks for this opportunity have been automatically
marked as complete.

┌─────────────────────────┐
│   View Quotation   │  ← Green button
└─────────────────────────┘

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is an automated notification from your Opportunity Management system.

Questions? Contact your sales manager or system administrator.
```

---

## Customization Options

### Option 1: Keep Current Simple Email
- ✅ Clean and concise
- ✅ Gets the message across
- ✅ Includes action button
- ✅ Already implemented

### Option 2: Upgrade to Enhanced Email
- ✅ More detailed information
- ✅ Shows customer name and amount
- ✅ Professional formatting
- ✅ Matches enterprise notification style
- ⚠️ Requires code update

### Option 3: Use Email Template Doctype
- ✅ Fully customizable via UI
- ✅ No code changes needed
- ✅ Can include custom fields
- ✅ Supports Jinja templating
- ⚠️ Need to create template first

---

## Which Option Do You Want?

### Quick Decision Guide:

**Choose Option 1 (Current)** if:
- You want it working now without changes
- Simple notifications are fine
- You don't need to customize frequently

**Choose Option 2 (Enhanced)** if:
- You want more professional emails
- Need to show more opportunity details
- Want consistency with enterprise style

**Choose Option 3 (Email Template)** if:
- You want to customize via UI (no coding)
- Different teams need different formats
- You want to use your existing templates

---

## Sample Email Template (Option 3)

If you choose Option 3, here's the Email Template you'd create:

### Template Name: "Opportunity Converted to Quotation"

**Subject:**
```jinja
Task Completed: Opportunity {{ doc.name }}
```

**Message:**
```jinja
<div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #28a745;">✅ Opportunity Converted</h2>

    <p>Hi {{ recipient_name }},</p>

    <p>The opportunity <strong>{{ opportunity_name }}</strong> has been successfully converted to a quotation.</p>

    <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
        <tr style="background-color: #f8f9fa;">
            <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Customer:</strong></td>
            <td style="padding: 10px; border: 1px solid #dee2e6;">{{ customer_name }}</td>
        </tr>
        <tr>
            <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Opportunity:</strong></td>
            <td style="padding: 10px; border: 1px solid #dee2e6;">{{ opportunity_name }}</td>
        </tr>
        <tr style="background-color: #f8f9fa;">
            <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Quotation:</strong></td>
            <td style="padding: 10px; border: 1px solid #dee2e6;">{{ quotation_name }}</td>
        </tr>
    </table>

    <p style="text-align: center; margin: 30px 0;">
        <a href="{{ quotation_link }}"
           style="background-color: #28a745; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; display: inline-block;">
            View Quotation
        </a>
    </p>

    <p style="color: #6c757d; font-size: 12px; margin-top: 30px; border-top: 1px solid #dee2e6; padding-top: 15px;">
        This is an automated notification. Your assigned tasks have been marked as complete.
    </p>
</div>
```

---

## How to Implement Each Option

### For Option 1 (Current - No Changes Needed)
Already implemented! ✅

### For Option 2 (Enhanced Email)
I can update the code in `quotation_handler.py` to use the enhanced template.

### For Option 3 (Email Template Doctype)
Steps:
1. Go to Setup > Email > Email Template
2. Create new template named "Opportunity Converted to Quotation"
3. Copy the template code above
4. Update `quotation_handler.py` to use the template

---

## Recommendation

**I recommend Option 1 (Current) for now** because:
1. ✅ It's already working
2. ✅ Clean and professional
3. ✅ Includes the essential information
4. ✅ Has action button
5. ✅ Won't spam users with too much info

You can always upgrade to Option 2 or 3 later if needed!

---

## Testing the Email

Want to see how it looks? Here's how to test:

```bash
bench --site [your-site] console
```

```python
# Test the email notification
from opportunity_management.quotation_handler import send_todo_closed_notification

# Create a test todo object
class TestTodo:
    allocated_to = "your.email@company.com"
    name = "TEST-TODO-001"

todo = TestTodo()

# Send test email
send_todo_closed_notification(
    todo=todo,
    opportunity_name="OPP-TEST-001",
    quotation_name="QTN-TEST-001"
)
```

You'll receive the email and can see exactly how it looks!

---

## Questions?

Let me know which option you prefer and I can:
1. Keep it as is (Option 1)
2. Upgrade to enhanced email (Option 2)
3. Create Email Template doctype (Option 3)
4. Customize to match your branding
5. Add more fields/information

What would you like to do?
