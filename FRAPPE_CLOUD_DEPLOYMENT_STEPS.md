# Frappe Cloud Deployment Steps for Team Opportunities UI Update

## Current Status
- ✅ Code pushed to `origin/development` (commit: `6e6be49`)
- ✅ Contains modern gradient cards, tabs, and row highlighting
- ❌ Not visible in deployed app (JavaScript cache issue)

## Issue
Frappe Cloud has the code, but the browser and Frappe are serving cached JavaScript files. You need to force a rebuild of the frontend assets.

## Solution: Clear Cache and Rebuild

### Step 1: Access Frappe Cloud Bench Console
1. Log into your Frappe Cloud dashboard
2. Navigate to your site
3. Open the "Bench Console" or "Site Console"

### Step 2: Run These Commands (in order)

```bash
# 1. Clear all caches
bench --site [your-site-name] clear-cache

# 2. Clear website cache specifically
bench --site [your-site-name] clear-website-cache

# 3. Rebuild all assets (JavaScript, CSS, etc.)
bench build --app opportunity_management

# 4. Restart the site
bench restart
```

Replace `[your-site-name]` with your actual site name (e.g., `mycompany.frappe.cloud`)

### Step 3: Clear Browser Cache
After running the commands above:

1. **Hard refresh** your browser:
   - **Windows/Linux**: `Ctrl + Shift + R`
   - **Mac**: `Cmd + Shift + R`

2. Or open in **Incognito/Private** window to test

## Alternative: Use Frappe UI

If you don't have console access, use the Frappe UI:

1. Log into your Frappe site as Administrator
2. Go to: `Developer > Clear Cache`
3. Click "Clear Cache" button
4. Go to: `System Settings`
5. Check "Build Assets"
6. Save
7. Wait 2-3 minutes for rebuild
8. Hard refresh browser

## What Should Change

After the cache clear and rebuild, **Team Opportunities** should show:

### Modern Gradient Cards:
- **Total Open**: Purple gradient (#667eea → #764ba2)
- **Overdue**: Pink-red gradient (#f093fb → #f5576c)
- **Due Today**: Pink-yellow gradient (#fa709a → #fee140)
- **Due in 3 days**: Peach gradient (#ffecd2 → #fcb69f)

### Tabs:
- "Open Opportunities" button (blue when active)
- "Completed Opportunities" button

### Row Highlighting:
- Rows for opportunities closing today: Yellow gradient background with orange left border

## Verification

Check that the file was deployed:
1. Open browser DevTools (F12)
2. Go to Network tab
3. Filter for "team_opportunities.js"
4. Hard refresh page
5. Click on the JavaScript file
6. Search for "linear-gradient" - you should see multiple matches

## If Still Not Working

### Check 1: Verify Deployment
In Frappe Cloud dashboard, check:
- Current deployed commit hash should be: `6e6be49` or later
- Branch should be: `development`

### Check 2: Check Build Status
Look for build errors in Frappe Cloud logs:
- If build failed, the new JavaScript won't be deployed
- Check the "Deployment Logs" section

### Check 3: Manual File Check
If you have SSH access:
```bash
# Check if the file exists and has the modern code
cat ~/frappe-bench/apps/opportunity_management/opportunity_management/page/team_opportunities/team_opportunities.js | grep "linear-gradient"
```

You should see multiple lines with gradient CSS.

## Files Updated

The following files contain the modern UI code:

1. **`team_opportunities.js`** - Frontend with gradient cards and tabs
2. **`my_opportunities.js`** - Reference (already working)
3. **`api.py`** - Backend with `include_completed` parameter

All files are in commit `6e6be49` on the `development` branch.

---

**Note**: If the issue persists after all these steps, there may be a CDN caching issue with Frappe Cloud. In that case, contact Frappe Cloud support or wait 10-15 minutes for the CDN cache to expire.
