# Why Am I Seeing Other People's ToDos?

## Possible Reasons

### Reason 1: You're Viewing "All ToDos" Instead of "My ToDos"

**Check the filter in your ToDo list:**

1. Go to: **Home → ToDo**
2. Look at the top filter bar
3. Check if there's a filter: **Allocated To = Your Name**

**If the filter is missing or set to "All":**
- You'll see everyone's ToDos
- **Solution:** Add filter: `Allocated To = [Your Name]`

---

### Reason 2: You Have System Manager or Administrator Role

**If you're a System Manager or Administrator:**
- Frappe shows you ALL records by default
- This is normal for admin users
- You have permission to see everyone's tasks

**To check your roles:**
1. Click your profile picture (top right)
2. Click "My Settings"
3. Scroll to "Roles" section
4. Look for: "System Manager" or "Administrator"

**If you see these roles:**
- This is why you see all ToDos
- This is expected behavior for admins
- You can still filter to see only yours

---

### Reason 3: Custom Permission Rules

**Your system might have custom permissions that show all ToDos to certain users.**

**To check:**
1. Go to: **Setup → Permissions → Role Permissions Manager**
2. Select Document Type: **ToDo**
3. Check permissions for your role

**Look for:**
- "If Owner" = No (means you can see all)
- "Apply User Permissions" = No (means no user-level restrictions)

---

### Reason 4: The ToDos Are Actually ALL Assigned to You

**This would be a REAL duplicate issue!**

**To verify:**
1. Go to: **Home → ToDo**
2. Click on one of the "other people's" ToDos
3. Check the **"Allocated To"** field

**If it shows YOUR email/user:**
- This is a duplicate problem
- All 3 ToDos are assigned to you (wrong!)
- Your client script has a bug

**If it shows someone else's email:**
- You just have permission to see all ToDos
- This is normal for admins

---

## Quick Test: Are They Really Others' ToDos?

### Open 3 ToDos from the same Opportunity:

```
ToDo #1:
- Allocated To: employee1@company.com  ← Employee 1
- Reference: OPP-2024-00123

ToDo #2:
- Allocated To: employee2@company.com  ← Employee 2
- Reference: OPP-2024-00123

ToDo #3:
- Allocated To: you@company.com  ← YOU
- Reference: OPP-2024-00123
```

**✅ If Allocated To is DIFFERENT for each → You just have admin permissions**

**❌ If Allocated To is the SAME (all you@company.com) → DUPLICATE BUG**

---

## How to Filter Your ToDo List (Show Only Yours)

### Method 1: Use Standard Filter

1. Go to: **Home → ToDo**
2. Click **Filter** button (top right)
3. Add filter:
   - Field: `Allocated To`
   - Operator: `=`
   - Value: `[Your Name/Email]`
4. Click **Apply**

Now you'll only see YOUR ToDos.

---

### Method 2: Create a Saved Filter

1. Go to: **Home → ToDo**
2. Add the filter (as above)
3. Click the **Star icon** next to filters
4. Name it: "My ToDos"
5. Save

Now you can quickly switch to "My ToDos" view.

---

### Method 3: Create a Custom Report

1. Go to: **Home → Report**
2. Click **New Report**
3. Report Type: **Report Builder**
4. Based on DocType: **ToDo**
5. Add Filter: `Allocated To = {current_user}`
6. Save report as: "My Open Tasks"

---

## Most Likely Scenario (Based on Your Setup)

**You're probably a System Manager or Administrator.**

**Why this is likely:**
- You're deploying custom apps
- You're creating notifications and email templates
- You have access to hooks.py and client scripts
- You're managing the ERP system

**System Managers see ALL records by default** - this is normal Frappe behavior.

---

## Verify This is NOT a Duplicate Issue

**Run this test:**

1. Open the Opportunity that has 3 assignees
2. Go to: **Home → ToDo**
3. Search for the opportunity name
4. You should see 3 ToDos
5. **Click each one and check "Allocated To" field:**

**Expected (CORRECT):**
```
ToDo #1 → Allocated To: employee1@company.com
ToDo #2 → Allocated To: employee2@company.com
ToDo #3 → Allocated To: you@company.com
```

**Duplicate Issue (WRONG):**
```
ToDo #1 → Allocated To: you@company.com
ToDo #2 → Allocated To: you@company.com
ToDo #3 → Allocated To: you@company.com
```

If you see the first pattern → **No duplicates, just admin view**

If you see the second pattern → **Real duplicate bug, need to investigate**

---

## If You Confirm It's a Duplicate Bug

**Possible causes:**

### 1. Employee Records Have Wrong User IDs

Check each employee:
1. Go to: **HR → Employee**
2. Open Employee #1
3. Check **User ID** field
4. Repeat for all employees

**If all employees have the same User ID (yours):**
- This is the problem!
- Fix: Update each employee with correct User ID

---

### 2. Client Script Getting Wrong User ID

Add debug logging to your client script:

```javascript
frappe.db.get_value('Employee', row.responsible_engineer, ['employee_name', 'user_id'], function(emp) {
    // ADD THIS LINE:
    console.log('Employee:', emp.employee_name, 'User ID:', emp.user_id);

    if (!emp || !emp.user_id) {
        console.log('No user_id for employee:', row.responsible_engineer);
        // ... rest of code
    }
});
```

Then:
1. Save an opportunity with 3 assignees
2. Open browser console (F12)
3. Check the log output
4. Verify each employee has a different user_id

---

### 3. Responsible Engineer Doctype Issue

Check the Responsible Engineer records:
1. Go to: **Search → Responsible Engineer**
2. Open each engineer
3. Check if there's a **user** or **employee** field
4. Verify it links to the correct Employee/User

---

## Quick Console Check (For Admins)

Run this in Developer Console to see all ToDos:

```python
# Get all ToDos for a specific opportunity
opportunity_name = "OPP-2024-00123"  # Replace with actual

todos = frappe.get_all("ToDo",
    filters={
        "reference_type": "Opportunity",
        "reference_name": opportunity_name
    },
    fields=["name", "allocated_to", "status", "description"]
)

print(f"\\n{'='*60}")
print(f"Total ToDos: {len(todos)}")
print(f"{'='*60}\\n")

for i, todo in enumerate(todos, 1):
    print(f"ToDo #{i}:")
    print(f"  Name: {todo.name}")
    print(f"  Allocated To: {todo.allocated_to}")
    print(f"  Status: {todo.status}")
    print(f"  Description: {todo.description[:50]}...")
    print()

# Check for duplicates
allocated_users = [t.allocated_to for t in todos]
unique_users = set(allocated_users)

print(f"Unique users: {len(unique_users)}")
print(f"Total ToDos: {len(todos)}")

if len(unique_users) < len(todos):
    print("\\n⚠️  DUPLICATE DETECTED!")
    print("Some users have multiple ToDos for this opportunity")

    from collections import Counter
    counts = Counter(allocated_users)
    for user, count in counts.items():
        if count > 1:
            print(f"  - {user}: {count} ToDos (should be 1)")
else:
    print("\\n✅ No duplicates - each user has exactly 1 ToDo")
```

---

## Summary

**Most likely:** You're seeing all ToDos because you're an Administrator/System Manager.

**To verify:** Check the "Allocated To" field on each ToDo.

**Solution:** Just add a filter to show only your ToDos.

**If it's a real duplicate:** Check employee User IDs and debug the client script.

---

**Next step: Tell me what you see in the "Allocated To" field when you open the "other people's" ToDos!**
