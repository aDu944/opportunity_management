# Opportunity Management for ERPNext

A custom Frappe app for managing opportunity assignments, notifications, and KPI tracking.

## Features

### 1. Individual ToDos from Child Table
- When an Opportunity is saved with engineers in the `custom_resp_eng` child table, a separate ToDo is created for each engineer
- A ToDo is also created for the user who assigned the opportunity
- No duplicate todos for the same user

### 2. Assignment Email Notifications
- When assigned, each engineer receives an email with:
  - Opportunity details
  - Customer name
  - Closing date
  - **List of items to be quoted** (from Opportunity Item table)
  - Direct link to the opportunity

### 3. Reminder Emails
- Automated reminders sent at:
  - 7 days before closing
  - 3 days before closing
  - 1 day before closing
  - On the closing date
- Each reminder includes items to quote and urgency indicators
- Reminders only sent once per interval (tracked via comments)

### 4. Auto-Close ToDos
- When a Quotation is submitted for an Opportunity, all related ToDos are automatically closed
- Completion notification sent to assignees
- Tracks whether completed on time

### 5. My Opportunities Page
- Personal dashboard for each employee
- Shows all open opportunities assigned to them
- Color-coded urgency indicators
- Direct "Create Quotation" button
- Filter by urgency level

### 6. Team Opportunities Page
- Shows all team opportunities without duplicates
- Filter by department/team
- See all assignees per opportunity
- Great for managers and team leads

### 7. KPI Dashboard
- Overall completion metrics
- On-time completion rate
- Breakdown by employee or by team
- Date range filtering
- Visual charts

## Installation

```bash
# Navigate to your bench folder
cd ~/frappe-bench

# Get the app
bench get-app https://github.com/your-org/opportunity_management.git
# Or copy the folder manually

# Install on your site
bench --site your-site.local install-app opportunity_management

# Run migrations
bench --site your-site.local migrate

# Build assets
bench build

# Restart
bench restart
```

## Configuration

### 1. Responsible Engineer Doctype
Ensure your "Responsible Engineer" doctype has these link fields:
- `employee` → Link to Employee
- `shareholder` → Link to Shareholder (optional)

The system will use the `user_id` from Employee to:
- Create ToDos
- Send emails

### 2. Opportunity Custom Field
Your `custom_resp_eng` field should be:
- Type: Table MultiSelect
- Options: Responsible Engineer

### 3. Email Setup
Ensure your ERPNext email settings are configured for outgoing emails.

## Pages

Access these pages from the awesome bar or sidebar:

| Page | URL | Description |
|------|-----|-------------|
| My Opportunities | `/app/my-opportunities` | Personal task list |
| Team Opportunities | `/app/team-opportunities` | Team-wide view |
| Opportunity KPI | `/app/opportunity-kpi` | Performance dashboard |

## Roles & Permissions

| Role | My Opportunities | Team Opportunities | KPI Dashboard |
|------|-----------------|-------------------|---------------|
| Sales User | ✅ | ❌ | ❌ |
| Sales Manager | ✅ | ✅ | ✅ |
| System Manager | ✅ | ✅ | ✅ |

## Scheduled Tasks

The app registers these scheduled tasks:

| Task | Frequency | Description |
|------|-----------|-------------|
| `send_opportunity_reminders` | Daily | Sends reminder emails |
| `check_and_close_todos` | Hourly | Catches any missed todo closures |

## Customization

### Modify Reminder Days
Edit `tasks.py`:
```python
reminder_days = [7, 3, 1, 0]  # Days before closing date
```

### Modify Email Templates
Edit the email templates in:
- `opportunity_handler.py` → `send_assignment_email()`
- `tasks.py` → `send_reminder_email()`

### Add Custom Fields to ToDo
If you want to track additional data, add custom fields to the ToDo doctype:
- `custom_closing_date` (Date)
- `custom_is_assigner` (Check)
- `custom_reminder_7_sent` (Check)
- `custom_reminder_3_sent` (Check)
- `custom_reminder_1_sent` (Check)
- `custom_reminder_0_sent` (Check)

## Troubleshooting

### Emails not sending
1. Check Email Account settings in ERPNext
2. Check Error Log for email errors
3. Verify email queue: `bench --site your-site.local show-pending-jobs`

### ToDos not being created
1. Check that `custom_resp_eng` contains valid Responsible Engineer links
2. Verify the Employee linked to Responsible Engineer has a `user_id`
3. Check Error Log for any Python errors

### Reminders not working
1. Check scheduler is running: `bench --site your-site.local scheduler status`
2. Run manually: `bench --site your-site.local execute opportunity_management.opportunity_management.tasks.send_opportunity_reminders`

## License

MIT
