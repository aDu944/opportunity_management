# Workspace Fix - Make Links Clickable and Show Icon

## Problem

- ✗ Workspace icon not showing (only "Opportunity Management" text)
- ✗ Clicking workspace shows headers but no clickable links
- ✗ Shows: "Views & Dashboards", "Reports & Logs", "Configuration" as text only

## Solution

Run the workspace fix script to properly register the workspace in the database.

---

## Quick Fix (2 minutes)

```bash
# Step 1: Go to your bench
cd ~/frappe-bench

# Step 2: Open console
bench --site [your-site] console

# Step 3: Run fix script
>>> from opportunity_management.fix_workspace import fix_workspace
>>> fix_workspace()

# Step 4: Clear cache
>>> exit()
bench --site [your-site] clear-cache
bench restart
```

Then refresh your browser (Ctrl+Shift+R).

---

## What This Does

The script will:
1. ✅ Find or create the "Opportunity Management" workspace
2. ✅ Set the briefcase icon properly
3. ✅ Add all shortcuts (Opportunity)
4. ✅ Add all clickable links:
   - My Opportunities
   - Team Opportunities
   - Opportunity Calendar
   - KPI Dashboard
   - Assignment Log
   - Employee Team Assignment
   - Email Templates
5. ✅ Save to database
6. ✅ Make it visible in sidebar

---

## Expected Result

### Before Fix:
```
📄 Opportunity Management  ← No icon, just text
  Views & Dashboards       ← Header only, not clickable
  Reports & Logs           ← Header only, not clickable
  Configuration            ← Header only, not clickable
```

### After Fix:
```
💼 Opportunity Management  ← Briefcase icon!

  Shortcuts
  📋 Opportunity

  My Opportunities         ← Clickable link!
  Team Opportunities       ← Clickable link!
  Opportunity Calendar     ← Clickable link!
  KPI Dashboard            ← Clickable link!

  Assignment Log           ← Clickable link!

  Employee Team Assignment ← Clickable link!
  Email Templates          ← Clickable link!
```

---

## Alternative: Nuclear Option

If the quick fix doesn't work, try the nuclear option (delete and recreate):

```bash
bench --site [your-site] console
```

```python
from opportunity_management.fix_workspace import delete_and_recreate_workspace
delete_and_recreate_workspace()
```

Then:
```bash
exit()
bench --site [your-site] clear-cache
bench restart
```

---

## Troubleshooting

### Issue: Still no icon after fix

**Try:**
```bash
# Clear all caches
bench --site [your-site] clear-cache
bench --site [your-site] clear-website-cache
bench build --app opportunity_management
bench restart
```

Then hard refresh browser: **Ctrl+Shift+F5** (or Cmd+Shift+R on Mac)

### Issue: Links still not clickable

**Check if pages exist:**
```bash
bench --site [your-site] console
```

```python
import frappe

# Check if pages exist
pages = [
    "my-opportunities",
    "team-opportunities",
    "opportunity-calendar",
    "opportunity-kpi",
    "employee-team-assignment"
]

for page in pages:
    exists = frappe.db.exists("Page", page)
    print(f"{page}: {'✓ Exists' if exists else '✗ Missing'}")
```

If any pages are missing, run migrate:
```bash
exit()
bench --site [your-site] migrate
```

### Issue: Workspace disappeared completely

**Recreate it:**
```bash
bench --site [your-site] console
```

```python
from opportunity_management.fix_workspace import delete_and_recreate_workspace
delete_and_recreate_workspace()
```

---

## Why This Happens

Frappe v14+ uses a new workspace system where:
- Workspaces must be in the database (not just JSON files)
- Icons need to be properly registered
- Links need specific format (`links` child table, not just `content` JSON)

The JSON file we created earlier uses the new format but wasn't imported into the database properly. The fix script does this correctly.

---

## Verification

After running the fix, verify it worked:

```bash
bench --site [your-site] console
```

```python
import frappe

workspace = frappe.get_doc("Workspace", "Opportunity Management")

print(f"Icon: {workspace.icon}")
print(f"Links: {len(workspace.links)}")
print(f"Shortcuts: {len(workspace.shortcuts)}")
print(f"Public: {workspace.public}")
print(f"Hidden: {workspace.is_hidden}")

# Should show:
# Icon: briefcase
# Links: 7
# Shortcuts: 1
# Public: 1
# Hidden: 0
```

---

## Manual Alternative (UI Method)

If you prefer to do it manually through the UI:

1. Go to **Setup > Workspace**
2. Find "Opportunity Management" workspace
3. Click to edit
4. Set icon to "briefcase"
5. Add links manually:
   - Click "Add Link"
   - Set Label, Link To, Type, Icon
   - Repeat for each page
6. Save

But the script is much faster! 😊

---

## Summary

**Quick fix:**
```bash
cd ~/frappe-bench
bench --site [your-site] console
>>> from opportunity_management.fix_workspace import fix_workspace
>>> fix_workspace()
>>> exit()
bench --site [your-site] clear-cache
bench restart
```

**Then refresh browser** and you should see:
- ✅ Briefcase icon
- ✅ All links clickable
- ✅ Proper sidebar menu

Done! 🎉
