# Frappe Cloud Deployment Guide

## For Frappe Cloud Hosting - Workspace Fix

Since you're on **Frappe Cloud**, you can't run console commands directly. Here are your options:

---

## Option 1: Reinstall the App (Easiest - Recommended)

This will trigger the `after_install()` hook which creates the workspace automatically.

### Steps:

1. **Go to your Frappe Cloud dashboard**
2. **Navigate to your site**
3. **Go to Apps section**
4. **Find "Opportunity Management" app**
5. **Click "Uninstall"** (don't worry, your data is safe)
6. **Click "Install" again**

This will run the installation script which now includes workspace creation!

**What gets reinstalled:**
- ✅ Workspace with icon and links
- ✅ Custom fields (if not already there)
- ❌ Your data is NOT affected (opportunities, quotations, etc.)

---

## Option 2: Update App from GitHub

If you have the app connected to GitHub:

### Steps:

1. **Make sure latest code is on GitHub** (already done ✅)
2. **Go to Frappe Cloud dashboard**
3. **Navigate to your site**
4. **Go to Apps section**
5. **Find "Opportunity Management"**
6. **Click "Update" or "Pull from Git"**
7. **Wait for deployment to complete**
8. **The workspace should be created automatically**

---

## Option 3: Run Script via Server Scripts (Advanced)

If you have access to Server Scripts in Frappe:

### Steps:

1. **Go to your site**
2. **Navigate to:**
   Setup > Automation > Server Script

3. **Create New Server Script:**
   - **Name:** Setup Opportunity Workspace
   - **Type:** API
   - **API Method:** opportunity_management.setup_workspace

4. **Script Code:**
```python
import frappe
from opportunity_management.opportunity_management.setup.install import create_workspace

create_workspace()
frappe.db.commit()

return {"message": "Workspace created successfully!"}
```

5. **Save**

6. **Run it once** by calling the API endpoint or clicking "Run"

---

## Option 4: Use Frappe Cloud Console (If Available)

Some Frappe Cloud plans have console access:

1. **Go to your site dashboard**
2. **Look for "Console" or "Shell" option**
3. **If available, run:**

```python
from opportunity_management.opportunity_management.setup.install import create_workspace
create_workspace()
frappe.db.commit()
```

---

## Option 5: Request Support to Run Command

Contact Frappe Cloud support and ask them to run:

```bash
bench --site your-site.frappe.cloud console
```

Then:
```python
from opportunity_management.opportunity_management.setup.install import create_workspace
create_workspace()
exit()
```

---

## After Workspace is Created

Once the workspace is created (through any method), you should see:

### In Sidebar (under PUBLIC):
```
💼 Opportunity Management
```

### When clicked, you'll see cards:

**Views & Dashboards**
- My Opportunities
- Team Opportunities
- Opportunity Calendar
- KPI Dashboard

**Reports & Logs**
- Assignment Log

**Configuration**
- Employee Team Assignment
- Email Templates

---

## Verification

To verify the workspace was created:

1. **Go to:** Setup > Workspace
2. **Search for:** "Opportunity Management"
3. **Open it**
4. **Check:**
   - Icon should be "briefcase"
   - Should have 3 cards
   - Each card should have links

---

## Troubleshooting

### Issue: App update doesn't create workspace

**Solution:** Try Option 1 (Reinstall)

### Issue: Can't uninstall app

**Reason:** You have data (opportunities, etc.)

**Solution:**
1. Use Option 3 (Server Script)
2. Or contact Frappe Cloud support

### Issue: Still showing headers only

**Check:**
1. Hard refresh browser (Ctrl+Shift+R)
2. Clear browser cache completely
3. Try different browser
4. Check if pages exist (go to /app/my-opportunities directly)

### Issue: Links exist but show 404

**Solution:** Run migrate on Frappe Cloud:
1. Go to site dashboard
2. Click "Migrate" button
3. Wait for completion
4. Refresh browser

---

## What Changed in Latest Update

The `install.py` file now includes:

```python
def after_install():
    create_opportunity_custom_fields()
    create_workspace()  # ← NEW!
    frappe.db.commit()
```

So when you reinstall or update the app, it will automatically create the workspace with proper structure for Frappe v15.

---

## Files Updated

- `opportunity_management/opportunity_management/setup/install.py` - Added workspace creation
- `opportunity_management/opportunity_management/setup/setup_workspace.py` - Standalone script

---

## Recommended Approach

**I recommend Option 1 (Reinstall App):**

1. ✅ Safest method
2. ✅ Guaranteed to work
3. ✅ Doesn't affect your data
4. ✅ Takes 2-3 minutes
5. ✅ No technical knowledge needed

Just go to your Frappe Cloud dashboard → Apps → Uninstall → Install

---

## Need Help?

If none of these options work, share:
1. Your Frappe Cloud plan (what features you have access to)
2. Screenshot of your Apps page
3. Any error messages you see

I can provide a more specific solution based on your access level!
