# 🚀 Deployment Checklist

## Pre-Installation Verification

- [x] All Python files syntax checked
- [x] All JavaScript files created
- [x] Workspace configuration created
- [x] API methods added for team functionality
- [x] Hooks properly configured
- [x] Documentation completed

---

## Installation Steps (Run in Order)

### Step 1: Navigate to Bench
```bash
cd ~/frappe-bench
# Or wherever your Frappe bench is located
```

### Step 2: Database Migration
```bash
bench --site [your-site] migrate
```
**Expected output:** "Migrated to..." with no errors

### Step 3: Clear Cache
```bash
bench --site [your-site] clear-cache
```
**Expected output:** "Cleared cache"

### Step 4: Rebuild Global Search
```bash
bench --site [your-site] rebuild-global-search
```
**Expected output:** "Rebuilt global search"

### Step 5: Build Assets
```bash
bench build --app opportunity_management
```
**Expected output:** Build completes successfully

### Step 6: Restart Bench
```bash
bench restart
```

**For production servers:**
```bash
sudo supervisorctl restart all
# OR
sudo service supervisor restart
```

---

## Post-Installation Testing

### ✅ Test 1: Verify Workspace Appears

1. Open your Frappe site in browser
2. Look at left sidebar
3. **Expected:** "Opportunity Management" appears in the workspace list
4. Click on it
5. **Expected:** Menu opens showing all items:
   - My Opportunities
   - Team Opportunities
   - Opportunity Calendar (NEW!)
   - KPI Dashboard
   - Assignment Log
   - Employee Team Assignment (NEW!)
   - Email Templates

**If workspace doesn't appear:**
```bash
bench --site [your-site] clear-cache
bench restart
# Then hard refresh browser (Ctrl+Shift+R)
```

---

### ✅ Test 2: Calendar View

1. Navigate to `/app/opportunity-calendar`
2. **Expected:** Calendar loads with current month
3. Click on different view buttons (Month/Week/List)
4. **Expected:** Views switch properly
5. Test filters (Status, Urgency, etc.)
6. **Expected:** Calendar updates based on filters

**If calendar doesn't load:**
- Check browser console for JavaScript errors
- Verify FullCalendar library is loaded
- Check page permissions

---

### ✅ Test 3: Employee Team Assignment

1. Navigate to `/app/employee-team-assignment`
2. **Expected:** Page loads with statistics cards
3. **Expected:** Table shows all active employees
4. Try selecting a department for an employee
5. **Expected:** Row highlights in yellow
6. Click "Save All Changes"
7. **Expected:** Success message appears
8. Verify in Employee master

**If page errors:**
- Check if Employee doctype exists
- Verify User and Department doctypes exist
- Check browser console for errors

---

### ✅ Test 4: Auto-Close Functionality

**Setup:**
1. Create a test Opportunity
2. Assign it to a user (creates ToDo)
3. Note the ToDo name

**Test:**
1. Create a Quotation linked to the Opportunity
2. Submit the Quotation
3. **Expected:** Success message about closing opportunity
4. Check Opportunity - **Status should be "Converted" or "Closed"**
5. Check ToDo - **Status should be "Closed"**
6. Check Assignment Log - **Should show completion**
7. Check assignee's email - **Should receive notification**

**If auto-close doesn't work:**
```bash
# Check error logs
bench --site [your-site] console

>>> frappe.get_all("Error Log", limit=5, order_by="creation desc")
```

---

### ✅ Test 5: Team Opportunities (Fixed API)

1. Navigate to `/app/team-opportunities`
2. **Expected:** Page loads without errors
3. **Expected:** Shows opportunities grouped by team
4. Test team filter dropdown
5. **Expected:** Filters work properly

**Previously showed error:** "no attribute 'get_team_opportunities'"
**Now fixed:** API methods added to `api.py`

---

## Verification Checklist

### Files Present
- [ ] `opportunity_management/opportunity_management/page/opportunity_calendar/`
  - [ ] `__init__.py`
  - [ ] `opportunity_calendar.py`
  - [ ] `opportunity_calendar.js`
  - [ ] `opportunity_calendar.json`

- [ ] `opportunity_management/opportunity_management/page/employee_team_assignment/`
  - [ ] `__init__.py`
  - [ ] `employee_team_assignment.py`
  - [ ] `employee_team_assignment.js`
  - [ ] `employee_team_assignment.json`

- [ ] `opportunity_management/opportunity_management/workspace/opportunity_management/`
  - [ ] `__init__.py`
  - [ ] `opportunity_management.json`

### Modified Files
- [ ] `opportunity_management/hooks.py` - Quotation hook added, workspace fixture added
- [ ] `opportunity_management/quotation_handler.py` - close_opportunity() function added
- [ ] `opportunity_management/opportunity_management/api.py` - Team API methods added

### Documentation
- [ ] `CALENDAR_FEATURE.md`
- [ ] `TEAM_ASSIGNMENT_GUIDE.md`
- [ ] `INSTALLATION_GUIDE.md`
- [ ] `DEPLOYMENT_CHECKLIST.md`

---

## Features Summary

### 1. Auto-Close on Quotation Submit
**Status:** ✅ Implemented
**What it does:**
- Closes Opportunity when Quotation is submitted
- Closes all related ToDos
- Updates Assignment Log
- Sends email notifications

**Hook location:** `opportunity_management/hooks.py` line 17-19

### 2. Calendar View
**Status:** ✅ Implemented
**Access:** `/app/opportunity-calendar`
**Features:**
- Month/Week/List views
- Color-coded by urgency
- Filterable
- Interactive event details

### 3. Employee Team Assignment
**Status:** ✅ Implemented
**Access:** `/app/employee-team-assignment`
**Features:**
- Bulk assign employees to departments
- Statistics dashboard
- Filters and search
- Create departments on-the-fly

### 4. Fixed Team API
**Status:** ✅ Fixed
**Methods added:**
- `get_team_opportunities(team=None)`
- `get_available_teams()`

### 5. Workspace Menu
**Status:** ✅ Created
**Location:** Left sidebar > "Opportunity Management"

---

## Rollback (If Needed)

If you need to rollback changes:

```bash
# Restore modified files
git checkout opportunity_management/hooks.py
git checkout opportunity_management/quotation_handler.py
git checkout opportunity_management/opportunity_management/api.py

# Remove new directories
rm -rf opportunity_management/opportunity_management/page/opportunity_calendar
rm -rf opportunity_management/opportunity_management/page/employee_team_assignment
rm -rf opportunity_management/opportunity_management/workspace

# Migrate and restart
bench --site [your-site] migrate
bench restart
```

---

## Troubleshooting Guide

### Issue: Workspace not visible
**Solution:**
```bash
bench --site [your-site] clear-cache
bench --site [your-site] rebuild-global-search
bench restart
```
Then hard refresh browser (Ctrl+Shift+R or Cmd+Shift+R)

### Issue: Calendar shows blank page
**Check:**
1. Browser console for JavaScript errors
2. Page permissions (need Sales User, Sales Manager, or System Manager role)
3. FullCalendar library loaded

**Fix:**
```bash
bench build --force
bench restart
```

### Issue: Employee Team Assignment errors
**Check:**
1. Employee doctype exists
2. Department doctype exists
3. Users are linked to employees

**Verify:**
```bash
bench --site [your-site] console

>>> frappe.get_all("Employee", limit=1)
>>> frappe.get_all("Department", limit=1)
```

### Issue: Auto-close not working
**Check:**
1. Quotation has opportunity field set
2. Hook is registered in hooks.py
3. No Python errors in Error Log

**Debug:**
```bash
bench --site [your-site] watch
# Then submit a quotation and watch for errors
```

### Issue: Team Opportunities API error
**Solution:** This should be fixed now with new API methods

**Verify:**
```bash
bench --site [your-site] console

>>> import opportunity_management.opportunity_management.api as api
>>> hasattr(api, 'get_team_opportunities')
# Should return: True
>>> hasattr(api, 'get_available_teams')
# Should return: True
```

---

## Performance Optimization (Optional)

### Database Indexes
```sql
-- Add index on department field for faster team queries
ALTER TABLE `tabEmployee` ADD INDEX `idx_department` (`department`);

-- Add index on expected_closing for calendar queries
ALTER TABLE `tabOpportunity` ADD INDEX `idx_expected_closing` (`expected_closing`);
```

### Scheduled Cleanup
Add to your scheduled tasks to clean up old assignment logs:
```python
# In hooks.py scheduler_events
"monthly": [
    "opportunity_management.utils.cleanup.archive_old_logs"
]
```

---

## Support & Next Steps

### Monitoring
```bash
# Watch logs in real-time
bench --site [your-site] watch

# Check error logs
bench --site [your-site] console
>>> frappe.get_all("Error Log", order_by="creation desc", limit=10)
```

### User Training
1. Share `TEAM_ASSIGNMENT_GUIDE.md` with HR managers
2. Share `CALENDAR_FEATURE.md` with sales teams
3. Train users on auto-close workflow

### Customization
All features are customizable:
- Colors in calendar (edit `get_urgency_color()`)
- Workspace layout (edit workspace JSON)
- Auto-close behavior (edit `quotation_handler.py`)

---

## ✅ Final Verification

All systems ready when:
- [ ] Workspace appears in sidebar
- [ ] Calendar view loads and shows data
- [ ] Employee Team Assignment page works
- [ ] Auto-close works on quotation submit
- [ ] Team Opportunities shows no API errors
- [ ] All documentation reviewed

---

**Status: READY FOR DEPLOYMENT** 🚀

Run the installation steps above and you're all set!
