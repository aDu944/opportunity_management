# ToDo Duplicate Check Guide

## How to Check If You Have Real Duplicates

### Scenario: You assigned 1 opportunity to 3 people (Employee1, Employee2, and Yourself)

---

## ✅ CORRECT Behavior (Not Duplicates):

**In the Opportunity:**
- 3 rows in `custom_resp_eng` table:
  - Row 1: Employee1
  - Row 2: Employee2
  - Row 3: You

**In the Database (all ToDos):**
- 3 ToDo records total:
  - ToDo #1: allocated_to = Employee1's user_id
  - ToDo #2: allocated_to = Employee2's user_id
  - ToDo #3: allocated_to = Your user_id

**In YOUR ToDo List (filtered to you):**
- 1 ToDo shown (only yours)

**Emails Sent:**
- 3 assignment emails (one per person) ✅ CORRECT

---

## ❌ DUPLICATE Behavior (Something is Wrong):

**In YOUR ToDo List:**
- 2 or 3 identical ToDos all assigned to YOU
- Same opportunity, same description, same date

**OR:**

**In the Database:**
- 6+ ToDo records for the same opportunity
- Multiple ToDos assigned to the same person

---

## How to Check in Frappe

### Method 1: Check Your ToDo List

1. Go to: **Home → ToDo**
2. Filter: **Allocated To = (Your Name)**
3. Search for the opportunity name
4. Count how many ToDos appear

**Expected:** 1 ToDo (for the specific opportunity)
**If you see:** 2+ identical ToDos → DUPLICATE ISSUE

---

### Method 2: Check All ToDos for One Opportunity

1. Go to: **Home → ToDo**
2. Click **Advanced Filters**
3. Add filters:
   - Reference Type = "Opportunity"
   - Reference Name = "OPP-2024-XXXXX" (your opportunity)
4. Remove the "Allocated To" filter to see ALL
5. Count total records

**Expected:** 3 ToDos (one per assignee)
**If you see:** 6+ ToDos → DUPLICATE ISSUE

---

### Method 3: Check Database Directly

Run this in Console (Developer mode):

```python
# Replace with your actual opportunity name
opportunity_name = "OPP-2024-00123"

todos = frappe.get_all("ToDo",
    filters={
        "reference_type": "Opportunity",
        "reference_name": opportunity_name
    },
    fields=["name", "allocated_to", "status", "creation"]
)

print(f"Total ToDos for {opportunity_name}: {len(todos)}")
for todo in todos:
    print(f"- {todo.name} → {todo.allocated_to} (Status: {todo.status})")
```

**Expected Output:**
```
Total ToDos for OPP-2024-00123: 3
- TODO-2024-00001 → employee1@company.com (Status: Open)
- TODO-2024-00002 → employee2@company.com (Status: Open)
- TODO-2024-00003 → you@company.com (Status: Open)
```

**Duplicate Problem:**
```
Total ToDos for OPP-2024-00123: 6
- TODO-2024-00001 → employee1@company.com (Status: Open)
- TODO-2024-00002 → employee1@company.com (Status: Open)  ← DUPLICATE!
- TODO-2024-00003 → employee2@company.com (Status: Open)
- TODO-2024-00004 → employee2@company.com (Status: Open)  ← DUPLICATE!
- TODO-2024-00005 → you@company.com (Status: Open)
- TODO-2024-00006 → you@company.com (Status: Open)  ← DUPLICATE!
```

---

## Common Confusion (Not Duplicates)

### "I see 3 ToDos in my list!"

**Check:** Are they for different opportunities?
- Opportunity A → 1 ToDo for you ✅
- Opportunity B → 1 ToDo for you ✅
- Opportunity C → 1 ToDo for you ✅
- **Total: 3 ToDos** (NOT duplicates - different opportunities)

### "My team says they each got an email!"

**This is correct!**
- 3 people assigned → 3 emails sent
- Each person gets notified
- This is WORKING AS INTENDED ✅

---

## What IS a Duplicate Email Problem?

**The duplicate email issue is:**

**Assignment:**
- 3 people assigned to Opportunity A
- **Expected:** 3 emails total (one per person)
- **Actual:** 3 emails ✅ CORRECT

**Reminders (3 days before closing):**
- 3 people assigned to Opportunity A
- **Expected:** 3 emails total (one per person)
- **Actual with bug:** 6 emails total
  - 3 from ToDo notifications
  - 3 from scheduled task
  - Each person gets 2 emails ❌ DUPLICATE

**This is what we fixed in NOTIFICATION_DUPLICATE_ANALYSIS.md**

---

## Your Client Script Analysis

Your client script is **preventing actual ToDo duplicates** with this code:

```javascript
// Check if already assigned
frappe.call({
    method: 'frappe.client.get_list',
    args: {
        doctype: 'ToDo',
        filters: {
            reference_type: 'Opportunity',
            reference_name: frm.doc.name,
            allocated_to: emp.user_id,
            status: 'Open'
        },
```

This checks if a ToDo already exists before creating a new one.

**Verdict:** Your client script is GOOD and NOT causing duplicates! ✅

---

## When Would You Have Real ToDo Duplicates?

**Only if:**

1. **Multiple systems creating ToDos:**
   - Client script creates ToDos
   - AND server-side hooks also create ToDos
   - Result: 2x ToDos for each person

2. **User clicks save multiple times rapidly:**
   - Your `is_processing_assignments` flag prevents this ✅

3. **Database transaction issues:**
   - The existence check fails
   - Rare, but can happen with timing issues

---

## Summary

✅ **Your client script is CORRECT**
✅ **3 ToDos for 3 people is EXPECTED**
✅ **Each person seeing 1 ToDo in their list is CORRECT**
✅ **3 assignment emails is CORRECT**

❌ **The duplicate issue is with REMINDER emails** (not ToDos)
❌ **Fix: Disable ToDo-based reminder notifications** (see NOTIFICATION_DUPLICATE_ANALYSIS.md)

---

## Recommendation

**Keep your client script exactly as it is!**

**To fix reminder email duplicates:**
1. Go to: Setup → Email → Notification
2. Disable notifications #2, #3, #4 (reminder notifications on ToDo)
3. Keep notification #1 enabled (assignment on ToDo)
4. Keep fancy scheduled task enabled (handles reminders)

**Result:**
- Assignment: 3 emails (one per person) ✅
- Reminders: 3 emails (one per person) ✅
- No duplicates! 🎉

---

**Still confused? Run Method 2 or Method 3 above to check your actual data!**
