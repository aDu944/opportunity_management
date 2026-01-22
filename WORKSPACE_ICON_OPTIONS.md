# Workspace Icon Options

## Current Icon

**Currently using:** `folder-normal`

This is a standard Frappe icon that will display properly.

---

## Other Good Options

If you want to change the icon, here are recommended alternatives from the Frappe icon set:

### Business/Organization Icons:
- `organization` - Building/company icon
- `project` - Project management icon
- `dashboard` - Dashboard/analytics icon
- `crm` - CRM module icon
- `sell` - Sales icon

### Folder/Document Icons:
- `folder-normal` ← **Current**
- `folder-open` - Open folder
- `file` - File icon

### General Icons:
- `star` - Star/favorite
- `card` - Card view
- `list` - List view

---

## How to Change the Icon

### Option 1: Edit in Code

Update `opportunity_management/opportunity_management/setup/install.py`:

```python
workspace = frappe.get_doc({
    "doctype": "Workspace",
    "name": workspace_name,
    "title": "Opportunity Management",
    "icon": "organization",  # ← Change this line
    ...
})
```

Then update the patch file `opportunity_management/patches/create_workspace.py` as well.

### Option 2: Edit via UI (After Deployment)

1. Go to **Setup > Workspace**
2. Find **"Opportunity Management"**
3. Click to edit
4. Change the **Icon** field
5. Save

Much easier! 😊

---

## Recommended Icon

For an Opportunity Management system, I recommend:

**Option 1:** `organization` - Professional, represents business
**Option 2:** `crm` - Since opportunities are part of CRM
**Option 3:** `dashboard` - Represents the analytics/tracking nature

---

## Current Status

✅ Changed from `briefcase` (not in standard set) to `folder-normal` (standard icon)

After your Frappe Cloud deployment completes, you can:
1. See the icon in the sidebar
2. Change it via UI if you want something different
3. No need to redeploy - UI changes take effect immediately

---

## Icon Preview

Once deployed, the workspace will show:

```
📁 Opportunity Management  ← folder-normal icon
```

If you change to `organization`:
```
🏢 Opportunity Management  ← organization icon
```

If you change to `dashboard`:
```
📊 Opportunity Management  ← dashboard icon
```

---

## Quick Change After Deployment

Don't like the folder icon? Here's the fastest way to change it:

1. **Navigate to:** `/app/workspace/Opportunity Management`
2. **Click:** Edit button
3. **Change:** Icon field to any from the list above
4. **Save**
5. **Refresh browser** - New icon appears instantly!

No code changes needed. ✨

---

*Note: The icon fix is already pushed to GitHub and will be included in your current deployment.*
