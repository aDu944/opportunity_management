# Opportunity Management - Complete Installation Guide

## 🎯 What's New

This update includes three major features:

1. **Auto-Close Functionality** - Opportunities and ToDos automatically close when Quotation is submitted
2. **Calendar View** - Visual calendar interface for tracking opportunities by closing date
3. **Employee Team Assignment** - Easy-to-use page for assigning employees to teams/departments

Plus:
- Fixed missing API methods for Team Opportunities page
- Created Workspace for left sidebar menu
- Updated documentation

---

## 📋 Installation Steps

### 1. Navigate to Bench Directory
```bash
cd ~/frappe-bench  # Or wherever your bench is located
```

### 2. Pull the Changes
If you're using Git, pull the latest changes to your site:
```bash
# If in a worktree, changes should already be there
cd sites/[your-site-name]
```

### 3. Run Migration
```bash
bench --site [your-site] migrate
```

This will:
- Register new pages in the database
- Set up the workspace
- Apply any schema changes

### 4. Clear Cache (Important!)
```bash
bench --site [your-site] clear-cache
```

This ensures:
- New pages are recognized
- Workspace appears in sidebar
- JavaScript files are reloaded

### 5. Rebuild Global Search
```bash
bench --site [your-site] rebuild-global-search
```

This makes the workspace searchable.

### 6. Build Assets
```bash
bench build --app opportunity_management
```

This compiles:
- JavaScript files
- CSS if any
- New page assets

### 7. Restart Bench
```bash
bench restart
```

Or if using production:
```bash
sudo service supervisor restart
# OR
sudo supervisorctl restart all
```

### 8. Verify Installation
1. Log into your site
2. Check left sidebar for "Opportunity Management" workspace
3. Click on it to see all menu items

---

## 🎨 What You Should See

### Left Sidebar Menu: "Opportunity Management"

When you click on it, you should see:

#### Shortcuts
- Opportunity
- New Opportunity

#### Views & Dashboards
- 👤 **My Opportunities** - Your assigned tasks
- 👥 **Team Opportunities** - Team view with filters
- 📅 **Opportunity Calendar** - NEW! Visual calendar view
- 📊 **KPI Dashboard** - Performance metrics

#### Reports & Logs
- 📋 **Assignment Log** - Track assignments

#### Configuration
- 👥 **Employee Team Assignment** - NEW! Bulk assign employees to teams
- 📧 **Email Templates** - Configure notifications

---

## ✅ Testing the Features

### Test 1: Auto-Close Functionality

1. **Create an Opportunity:**
   - Go to CRM > Opportunity
   - Create a new opportunity
   - Save it

2. **Assign it to a User:**
   - This creates a ToDo
   - Note the ToDo ID

3. **Create a Quotation:**
   - Go to Selling > Quotation
   - Create quotation
   - Link it to the opportunity
   - Save

4. **Submit the Quotation:**
   - Click "Submit"

5. **Verify:**
   - Opportunity status should be "Converted" or "Closed"
   - Related ToDos should be "Closed"
   - Check Assignment Log for updates
   - Assignees should receive email notifications

### Test 2: Calendar View

1. **Navigate to Calendar:**
   - Go to Opportunity Management > Opportunity Calendar
   - Or visit `/app/opportunity-calendar`

2. **What to Check:**
   - Calendar loads with month view
   - Opportunities appear on their closing dates
   - Color coding by urgency (Red, Orange, Yellow, Green)
   - Click event to see details
   - Use filters (Status, Urgency, Owner, Engineer)
   - Switch between Month, Week, List views

3. **Create a Test Opportunity:**
   - Set closing date to today or this week
   - Save
   - Check if it appears on the calendar
   - Verify color matches urgency

### Test 3: Employee Team Assignment

1. **Navigate to Team Assignment:**
   - Go to Opportunity Management > Employee Team Assignment
   - Or visit `/app/employee-team-assignment`

2. **Check Statistics:**
   - Should show total employees
   - Show how many are assigned/unassigned
   - Show department breakdown

3. **Assign an Employee:**
   - Find an employee in the table
   - Select department from dropdown
   - Click "Save All Changes"
   - Verify in Employee master

4. **Create a Department:**
   - Click "Create Department"
   - Enter name (e.g., "Sales")
   - Verify it appears in dropdowns

5. **Bulk Assignment:**
   - Assign multiple employees
   - Note rows turn yellow
   - Save all at once
   - Verify in Team Opportunities page

---

## 🔧 Troubleshooting

### Workspace Not Showing in Sidebar?

**Solution:**
```bash
bench --site [your-site] clear-cache
bench --site [your-site] rebuild-global-search
bench restart
```

Then refresh your browser (Ctrl+Shift+R or Cmd+Shift+R).

### Calendar Not Loading?

**Check:**
1. Browser console for JavaScript errors
2. FullCalendar library is loaded (bundled with Frappe)
3. Page permissions (Sales User, Sales Manager, System Manager)

**Fix:**
```bash
bench build --app opportunity_management
bench restart
```

### Auto-Close Not Working?

**Verify:**
1. Hook is registered: Check `hooks.py` for Quotation submit hook
2. Quotation has `opportunity` field set
3. Check Error Log doctype for any Python errors

**Debug:**
```bash
# Watch logs in real-time
bench --site [your-site] watch

# Then submit a quotation and watch for errors
```

### Team Opportunities Shows "No Attribute" Error?

**Fixed!** The missing API methods have been added:
- `get_team_opportunities()`
- `get_available_teams()`

If still occurring:
```bash
bench --site [your-site] migrate
bench restart
```

### Employees Not Showing in Team View?

**Check:**
1. Employee has User ID linked (go to Employee master)
2. Employee has Department assigned
3. Employee's user has active ToDos for opportunities
4. Run Employee Team Assignment page to verify

---

## 📁 Files Changed/Added

### Modified Files:
```
opportunity_management/hooks.py
opportunity_management/quotation_handler.py
opportunity_management/opportunity_management/api.py
```

### New Directories:
```
opportunity_management/opportunity_management/page/opportunity_calendar/
opportunity_management/opportunity_management/page/employee_team_assignment/
opportunity_management/opportunity_management/workspace/
```

### New Pages:
1. **Opportunity Calendar** (`opportunity-calendar`)
2. **Employee Team Assignment** (`employee-team-assignment`)

### New Documentation:
```
CALENDAR_FEATURE.md
TEAM_ASSIGNMENT_GUIDE.md
INSTALLATION_GUIDE.md (this file)
```

---

## 🔐 Permissions

### Calendar View
- System Manager
- Sales Manager
- Sales User

### Employee Team Assignment
- System Manager
- HR Manager

### Auto-Close Functionality
- Works automatically on Quotation submit
- No special permissions needed

---

## 🎓 Quick Start Workflow

### Day 1: Setup Teams
1. Create departments (Sales, Engineering, Support, etc.)
2. Assign employees to departments
3. Link employees to user accounts

### Day 2: Configure Opportunities
1. Create opportunities with closing dates
2. Assign to team members (creates ToDos)
3. Set urgency levels

### Day 3: Use the Tools
1. Team members check "My Opportunities"
2. Managers use "Team Opportunities" to monitor
3. Use Calendar view for planning
4. Review KPI Dashboard for metrics

### Ongoing: Close Opportunities
1. Create quotations from opportunities
2. Submit quotations (auto-closes everything)
3. Review Assignment Log for completed work

---

## 📊 Integration Points

### Works With:
- ERPNext CRM (Opportunity, Quotation)
- HR Module (Employee, Department)
- Email system (notifications)
- ToDo system (task tracking)

### Data Flow:
```
Opportunity Created
    ↓
Assigned to User
    ↓
ToDo Created
    ↓
Shows in My Opportunities
    ↓
Shows in Team Opportunities (by department)
    ↓
Visible on Calendar (by closing date)
    ↓
Quotation Created & Submitted
    ↓
AUTO: Opportunity Closed
AUTO: ToDos Closed
AUTO: Assignment Log Updated
AUTO: Email Notifications Sent
    ↓
Appears in KPI Metrics
```

---

## 🚀 Performance Tips

1. **Large Datasets:**
   - Calendar loads only date range visible
   - Use filters to reduce data

2. **Team Opportunities:**
   - Index the department field on Employee
   - Filter by team to reduce queries

3. **Assignment Log:**
   - Archive old logs periodically
   - Use date filters in KPI

---

## 📞 Support

### Check Logs:
```bash
# Real-time log watching
bench --site [your-site] watch

# Error log
bench --site [your-site] console
>>> frappe.db.sql("SELECT * FROM `tabError Log` ORDER BY creation DESC LIMIT 10")
```

### Common Issues:
- Check `CALENDAR_FEATURE.md` for calendar-specific issues
- Check `TEAM_ASSIGNMENT_GUIDE.md` for team setup issues
- Review browser console for JavaScript errors

### Report Issues:
- Include error log
- Steps to reproduce
- Frappe/ERPNext version

---

## 🎉 You're All Set!

Your Opportunity Management system now has:
- ✅ Auto-closing on quotation submit
- ✅ Visual calendar view
- ✅ Easy team assignment
- ✅ Complete workspace menu
- ✅ All API methods working

Enjoy your enhanced opportunity tracking! 🚀
