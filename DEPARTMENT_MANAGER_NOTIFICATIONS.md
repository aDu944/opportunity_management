# Department Manager Notifications Setup

## Overview

This feature automatically includes **department managers** in opportunity reminder notifications, so managers are kept in the loop alongside the responsible engineers.

## Who Receives Notifications Now?

### Before This Update:
- ✅ Responsible engineers assigned to the opportunity

### After This Update:
- ✅ Responsible engineers assigned to the opportunity
- ✅ **Department managers/heads** of the person who assigned the opportunity
- ✅ **System Managers** from the same department

## How It Works

```
User A (from Sales Department) assigns Opportunity to Engineer B
         ↓
System identifies User A's department: "Sales"
         ↓
System finds all managers in Sales Department:
  - Department Head
  - Employees with Manager/Head/Director designation
  - System Managers in Sales Department
         ↓
Reminder emails sent to:
  ✅ Engineer B (responsible engineer)
  ✅ Manager C (Sales Department Head)
  ✅ Manager D (System Manager in Sales)
```

---

## Manager Detection Logic

The system identifies managers using these criteria:

### Method 1: Department Structure
- Employee is listed as **Department Head** in the Department doctype
- Employee **reports to no one** (top of hierarchy)
- Employee has **designation** containing: "Manager", "Head", or "Director"

### Method 2: User Roles
- User has **System Manager** role
- User is in the same department as the assigner

---

## Example Scenarios

### Scenario 1: Sales Manager Assigns Opportunity

**Setup:**
- User: Ahmed (Sales Manager)
- Department: Sales
- Department Head: Fatima
- System Manager in Sales: Ali

**Action:**
- Ahmed assigns Opportunity to Engineer Omar

**Reminder emails sent to:**
1. ✅ Omar (responsible engineer)
2. ✅ Fatima (department head)
3. ✅ Ali (system manager in Sales)
4. ✅ Ahmed (if he's also a manager/system manager)

**Total: 3-4 emails per reminder**

---

### Scenario 2: Engineer Assigns Without Manager

**Setup:**
- User: Zaid (Junior Engineer)
- Department: Engineering
- No department head configured
- No system managers in Engineering

**Action:**
- Zaid assigns Opportunity to Engineer Sara

**Reminder emails sent to:**
1. ✅ Sara (responsible engineer)

**Total: 1 email** (no managers found)

---

### Scenario 3: Multi-Department Assignment

**Setup:**
- User A (Sales Manager) assigns to Engineer B (Engineering)
- Sales Department Head: Manager C
- Engineering Department Head: Manager D

**Reminder emails sent to:**
1. ✅ Engineer B (responsible engineer)
2. ✅ Manager C (Sales dept head - person who assigned)
3. ❌ Manager D (NOT included - different department)

**Logic:** Managers are from the **assigner's** department, not the engineer's department.

---

## Configuration Requirements

### 1. Employee Records Must Be Set Up

**Each employee needs:**
- ✅ **User ID** field populated
- ✅ **Department** field set
- ✅ **Status** = "Active"

**To check:**
1. Go to: **HR → Employee**
2. Open each employee
3. Verify User ID and Department are filled

---

### 2. Department Heads Must Be Configured

**To set department head:**
1. Go to: **HR → Department**
2. Open the department (e.g., "Sales")
3. Set **Department Head** field to the manager's employee record
4. Save

---

### 3. System Manager Role (Optional)

**To give System Manager role:**
1. Go to: **Users → User**
2. Open the user
3. Scroll to **Roles** section
4. Add role: **System Manager**
5. Save

---

## Testing the Feature

### Test Case 1: Verify Manager Lookup

**Run this in Console (Developer mode):**

```python
from opportunity_management.opportunity_management.notification_utils import get_department_managers

# Replace with your email
user_email = "ahmed@company.com"

managers = get_department_managers(user_email)

print(f"Managers for {user_email}:")
for mgr in managers:
    print(f"  - {mgr}")

if not managers:
    print("No managers found!")
    print("Check:")
    print("1. Employee record has department set")
    print("2. Department has a head configured")
    print("3. Or users with System Manager role exist in the department")
```

---

### Test Case 2: Verify Opportunity Recipients

**Run this in Console:**

```python
from opportunity_management.opportunity_management.notification_utils import get_opportunity_notification_recipients

# Replace with your opportunity name
opp_name = "OPP-2024-00123"

recipients = get_opportunity_notification_recipients(opp_name)

print(f"\\nRecipients for {opp_name}:")
print(f"Total: {len(recipients)} people\\n")

for email in recipients:
    user = frappe.get_doc("User", email)
    emp = frappe.db.get_value("Employee", {"user_id": email}, ["employee_name", "department"], as_dict=True)

    print(f"  - {email}")
    print(f"    Name: {user.full_name}")
    if emp:
        print(f"    Employee: {emp.employee_name}")
        print(f"    Department: {emp.department}")
    print()
```

---

### Test Case 3: End-to-End Test

1. **Create a test opportunity** with closing date 3 days from now
2. **Assign to an engineer** (as a manager from a specific department)
3. **Wait for 8 AM** (or manually trigger the scheduled task)
4. **Check email logs** to see who received emails

**Expected:**
- Engineer receives email ✅
- Department managers receive email ✅

---

## Troubleshooting

### Problem: Managers Not Receiving Emails

**Solution 1: Check Employee Records**
```python
# Check if employee has user_id
emp = frappe.get_doc("Employee", "EMP-00001")
print(f"User ID: {emp.user_id}")
print(f"Department: {emp.department}")
print(f"Status: {emp.status}")
```

**If user_id is empty:**
1. Go to: HR → Employee
2. Open the employee
3. Set **User ID** field to their email/user
4. Save

---

**Solution 2: Check Department Head**
```python
# Check department configuration
dept = frappe.get_doc("Department", "Sales")
print(f"Department Head: {dept.department_head}")
```

**If department_head is empty:**
1. Go to: HR → Department
2. Open the department
3. Set **Department Head** to the manager's employee record
4. Save

---

**Solution 3: Check System Manager Role**
```python
# Check who has System Manager role in a department
managers = frappe.db.sql("""
    SELECT e.employee_name, e.user_id, e.department
    FROM `tabEmployee` e
    INNER JOIN `tabHas Role` hr ON hr.parent = e.user_id
    WHERE e.department = 'Sales'
        AND hr.role = 'System Manager'
        AND e.status = 'Active'
""", as_dict=True)

for mgr in managers:
    print(f"{mgr.employee_name} - {mgr.user_id}")
```

---

### Problem: Too Many People Receiving Emails

**If too many managers are getting emails:**

The system finds managers based on:
- Department Head
- Designation containing "Manager", "Head", "Director"
- System Manager role

**To limit:**

1. **Option A: Remove System Manager role** from users who shouldn't receive notifications
2. **Option B: Change designations** to not include "Manager" keywords
3. **Option C: Modify the detection logic** in `notification_utils.py`

---

### Problem: Wrong Department Managers

**The system looks at the assigner's department, not the engineer's department.**

**Example:**
- Sales Manager assigns to Engineering Engineer
- Sales Managers get notified (CORRECT)
- Engineering Managers do NOT get notified (CORRECT)

**Rationale:** The managers who assigned the work should track it.

**To change this:** Modify `notification_utils.py` to look at engineer's department instead.

---

## Customization Options

### Option 1: Notify Engineer's Department Instead

**Edit:** `notification_utils.py`

**Change from:**
```python
# Get managers from the assigner's department
assigner_email = doc.owner or doc.modified_by
dept_managers = get_department_managers(assigner_email)
```

**Change to:**
```python
# Get managers from each engineer's department
for row in opportunity.custom_resp_eng:
    if row.responsible_engineer:
        emp = frappe.get_doc("Employee", row.responsible_engineer)
        if emp.user_id:
            dept_managers = get_department_managers(emp.user_id)
            recipients.update(dept_managers)
```

---

### Option 2: Only Notify Department Head (Not All Managers)

**Edit:** `notification_utils.py` → `get_department_managers()`

**Replace the SQL queries with:**
```python
# Only get the designated department head
dept = frappe.get_doc("Department", department)

if dept.department_head:
    emp = frappe.get_doc("Employee", dept.department_head)
    if emp.user_id:
        return [emp.user_id]

return []
```

---

### Option 3: Add Custom Field to Enable/Disable Manager Notifications

**1. Add custom field to Opportunity:**
- Field: `custom_notify_managers`
- Type: Check
- Label: "Notify Department Managers"

**2. Modify `get_all_recipients()` in tasks.py:**
```python
# Only include managers if checkbox is enabled
if doc.get("custom_notify_managers"):
    dept_managers = get_department_managers(assigner_email)
    recipients.update(dept_managers)
```

---

## Files Modified

### 1. `notification_utils.py` (NEW)
- `get_department_managers(user_email)` - Finds managers in user's department
- `get_opportunity_notification_recipients(opportunity_name)` - Gets all recipients
- Helper function for notifications

### 2. `tasks.py` (MODIFIED)
- `send_reminder_to_all_engineers()` - Now includes managers
- `get_all_recipients()` - NEW function that combines engineers + managers
- Existing `get_assigned_engineers()` - Kept unchanged for backward compatibility

---

## Email Preview

**Manager receives the same reminder email as engineers:**

```
┌────────────────────────────────────────┐
│ Important Reminder (3 days)            │ ← Orange header
│ Opportunity ID: #OPP-2024-00123       │
├────────────────────────────────────────┤
│ Dear Manager Ahmed,                    │
│                                        │
│ Important reminder! This opportunity   │
│ is closing in 3 days.                  │
│                                        │
│ [Opportunity details table]            │
│ [Items table]                          │
│                                        │
│     [ Take Action Now ]                │
└────────────────────────────────────────┘
```

**Note:** Email greeting uses the manager's name from User record.

---

## Summary

✅ **Added:** Department manager notifications
✅ **Recipients:** Engineers + Department managers + System managers
✅ **Logic:** Managers from assigner's department (not engineer's)
✅ **Detection:** Department head + Manager designation + System Manager role
✅ **Files:** `notification_utils.py` (new) + `tasks.py` (modified)
✅ **Testing:** Console commands provided
✅ **Customizable:** Multiple configuration options available

**Next Steps:**
1. Deploy to Frappe Cloud
2. Configure Department Heads in HR → Department
3. Test with console commands
4. Verify emails are received by both engineers and managers

---

**Questions or issues?** Check the troubleshooting section or run the test cases above!
