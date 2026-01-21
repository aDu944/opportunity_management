# Quick Fix Instructions

## Issues Fixed

1. ✅ **Calendar Error** - Fixed "Unknown column 'custom_resp_eng'" error
2. ✅ **Existing Open ToDos** - Created cleanup script to close old ToDos

---

## Step 1: Deploy the Fixes

```bash
# Navigate to your app in frappe bench
cd ~/frappe-bench/apps/opportunity_management

# Pull the latest changes from main
git pull origin main

# Go back to bench root
cd ~/frappe-bench

# Clear cache and rebuild
bench --site [your-site] clear-cache
bench build --app opportunity_management
bench restart
```

The calendar should now work! ✅

---

## Step 2: Clean Up Existing ToDos

You mentioned many open ToDos should be closed since they have submitted quotations. Here's how to fix that:

### Option A: Dry Run First (Recommended)

See what would be closed without making changes:

```bash
cd ~/frappe-bench
bench --site [your-site] console
```

Then in the console:
```python
from opportunity_management.cleanup_todos import cleanup_todos

# Dry run - shows what would be closed
cleanup_todos(dry_run=True)
```

This will show you:
- Which opportunities have submitted quotations
- Which ToDos would be closed
- Which opportunities would be closed

### Option B: Actually Close Them

If the dry run looks good, run it for real:

```python
from opportunity_management.cleanup_todos import cleanup_todos

# Actually close the ToDos
cleanup_todos(dry_run=False)
```

This will:
- ✅ Close all open ToDos for opportunities with submitted quotations
- ✅ Change opportunity status to "Converted"
- ✅ Add a comment to each opportunity explaining the auto-close
- ✅ Commit the changes to database

---

## Step 3: Check Draft Quotations (Optional)

To see opportunities with DRAFT quotations (not submitted):

```python
from opportunity_management.cleanup_todos import cleanup_draft_quotations

cleanup_draft_quotations()
```

**Note:** Draft quotations are NOT auto-closed. You need to submit them manually, then the auto-close will trigger.

---

## What the Cleanup Script Does

### For Submitted Quotations:
1. Finds all Quotations with `docstatus=1` (submitted)
2. Gets the linked Opportunity
3. Closes all open ToDos for that Opportunity
4. Changes Opportunity status to "Converted" if not already closed
5. Adds a comment explaining what happened

### Safety Features:
- ✅ Dry run mode to preview changes
- ✅ Only touches opportunities with SUBMITTED quotations
- ✅ Adds audit trail (comments)
- ✅ Shows detailed output of what's being changed

---

## Example Output

When you run the cleanup, you'll see output like this:

```
======================================================================
CLEANING UP TODOS FOR OPPORTUNITIES WITH SUBMITTED QUOTATIONS
======================================================================

Found 15 submitted quotations with linked opportunities

📋 Opportunity: OPP-2024-00123
   Quotation: QTN-2024-00456 (submitted)
   Status: Open
   Open ToDos: 3
   ✓ Closed ToDo: TODO-2024-00789 (assigned to: user@example.com)
   ✓ Closed ToDo: TODO-2024-00790 (assigned to: user2@example.com)
   ✓ Closed ToDo: TODO-2024-00791 (assigned to: user3@example.com)
   ✓ Closed Opportunity: OPP-2024-00123

======================================================================
SUMMARY
======================================================================
Opportunities with submitted quotations: 15
Opportunities processed: 15

ToDos closed: 45
Opportunities closed: 12

✅ Cleanup complete!
======================================================================
```

---

## Going Forward

### Auto-Close is Now Active

For NEW quotations (from now on):
- When you SUBMIT a quotation, the system will automatically:
  - Close the linked Opportunity
  - Close all related ToDos
  - Update Assignment Log
  - Send email notifications

### For Existing Data:
- Run the cleanup script once (Step 2 above)
- This is a one-time operation to fix historical data

---

## Troubleshooting

### If cleanup script shows errors:

**Check if you have the right permissions:**
```python
# In bench console
frappe.set_user("Administrator")
from opportunity_management.cleanup_todos import cleanup_todos
cleanup_todos(dry_run=False)
```

### If calendar still shows errors:

1. Check which custom fields you actually have:
```python
# In bench console
meta = frappe.get_meta("Opportunity")
print([f.fieldname for f in meta.fields if f.fieldname.startswith('custom_')])
```

2. The calendar now works WITHOUT these custom fields:
   - `custom_resp_eng` (falls back to opportunity_owner)
   - `custom_urgency_level` (won't filter, but calendar still works)
   - `custom_closing_date` (falls back to expected_closing)

---

## Summary

1. **Deploy Fixes** - Pull, clear cache, rebuild ✅
2. **Run Cleanup** - Close old ToDos with `cleanup_todos()` ✅
3. **Test** - Try the calendar and create a new quotation ✅

From now on, everything works automatically! 🎉
