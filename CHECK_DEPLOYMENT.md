# Diagnostic Steps for Team Opportunities Deployment Issue

## The Problem
Team Opportunities page shows old flat cards instead of modern gradient cards, despite code being pushed to development branch.

## Root Cause Analysis

The issue is likely one of these:

1. **Frappe Cloud didn't run `bench build`** after deployment
2. **CDN/Browser cache** is serving old files
3. **Wrong branch deployed** in Frappe Cloud settings

## Step 1: Verify What's Deployed in Frappe Cloud

### In Frappe Cloud Console, run:
```bash
# Check current git commit
cd ~/frappe-bench/apps/opportunity_management
git log -1 --oneline
```

**Expected output:** Should show commit `74e4bb1` or later with message "Add version comment to force cache invalidation"

**If different:** Frappe Cloud is deploying a different branch. Check Frappe Cloud settings to ensure `development` branch is selected.

---

## Step 2: Check if the JavaScript File Has Modern Code

### In Frappe Cloud Console, run:
```bash
# Search for modern gradient code in the deployed file
cd ~/frappe-bench/apps/opportunity_management
grep "linear-gradient" opportunity_management/page/team_opportunities/team_opportunities.js | head -3
```

**Expected output:** Should show lines like:
```
background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
background: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
```

**If NO output:** The file doesn't have the modern code. Git pull didn't work or wrong branch deployed.

**If SHOWS output:** File has the code but assets weren't built. Continue to Step 3.

---

## Step 3: Force Rebuild Assets

### In Frappe Cloud Console, run these commands IN ORDER:

```bash
# 1. Clear all caches
bench --site [your-site-name] clear-cache

# 2. Clear website cache
bench --site [your-site-name] clear-website-cache

# 3. Build assets for the app
bench build --app opportunity_management --force

# 4. Or build all assets
bench build --force

# 5. Restart bench
bench restart
```

Replace `[your-site-name]` with your actual site name.

---

## Step 4: Verify Built Assets Exist

### Check if built assets were created:
```bash
# Look for built JavaScript files
ls -lh ~/frappe-bench/sites/assets/opportunity_management/page/team_opportunities/

# Check build timestamp
ls -lhtr ~/frappe-bench/sites/assets/js/ | tail -5
```

The files should have recent timestamps (within the last few minutes).

---

## Step 5: Browser Cache Clear

After the build completes:

1. **Hard Refresh:** `Ctrl + Shift + R` (Windows/Linux) or `Cmd + Shift + R` (Mac)
2. **Or Clear Browser Cache:**
   - Chrome: Settings → Privacy → Clear browsing data → Cached images and files
3. **Or Open Incognito/Private Window**

---

## Alternative: Manual File Verification

If you have SSH/SFTP access, download this file:
```
~/frappe-bench/sites/assets/opportunity_management/page/team_opportunities/team_opportunities.bundle.js
```

Search for `linear-gradient` in the downloaded file. If it's NOT there, the build didn't include your changes.

---

## If Still Not Working: Check Build Logs

### In Frappe Cloud Dashboard:
1. Go to your site's **Deployment Logs**
2. Look for the most recent deployment
3. Check if you see:
   ```
   Running bench build
   Building assets...
   ```
4. Look for any **errors** during the build process

Common errors:
- JavaScript syntax errors (would prevent build)
- Permission issues
- Out of memory errors

---

## Nuclear Option: Force Complete Rebuild

If nothing else works, try this in Frappe Cloud Console:

```bash
# Remove all built assets
rm -rf ~/frappe-bench/sites/assets/*

# Rebuild everything
bench build --force

# Clear cache again
bench --site [your-site-name] clear-cache

# Restart
bench restart
```

**Warning:** This will rebuild ALL assets for ALL apps, which may take several minutes.

---

## Expected Final Result

After successful deployment and cache clear, Team Opportunities should show:

**Cards:**
- Purple gradient (Total Open): `#667eea → #764ba2`
- Pink-red gradient (Overdue): `#f093fb → #f5576c`
- Pink-yellow gradient (Due Today): `#fa709a → #fee140`
- Peach gradient (Due in 3 days): `#ffecd2 → #fcb69f`

**Tabs:**
- "Open Opportunities" button (blue when active)
- "Completed Opportunities" button

**Row highlighting:**
- Yellow gradient for rows closing today

---

## Quick Checklist

- [ ] Frappe Cloud deployed commit `74e4bb1` or later
- [ ] File contains `linear-gradient` code
- [ ] Ran `bench build --app opportunity_management --force`
- [ ] Cleared site cache
- [ ] Restarted bench
- [ ] Hard refreshed browser
- [ ] Still seeing old cards? Check deployment logs for errors

---

## Contact Points

If the issue persists after ALL these steps:

1. **Check Frappe Cloud support** - There may be a platform-level caching issue
2. **Verify branch settings** - Ensure development branch is selected in Frappe Cloud dashboard
3. **Check for build errors** - Review deployment logs for JavaScript errors

The code is definitely in the repository (verified at commit `74e4bb1`). The issue is purely deployment/caching related.
