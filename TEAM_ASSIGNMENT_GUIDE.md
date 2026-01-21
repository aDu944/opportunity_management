# Employee Team Assignment - User Guide

## Overview

The Employee Team Assignment page provides an easy-to-use interface for managing which employees belong to which teams (departments). This is crucial for the Team Opportunities view to work correctly.

## Access

Navigate to: **Opportunity Management > Employee Team Assignment**

Or directly: `/app/employee-team-assignment`

## Features

### 1. **Dashboard Statistics**
View at-a-glance stats:
- Total Employees
- Assigned to Teams
- Unassigned
- Linked to Users

### 2. **Department Breakdown**
See how many employees are in each department.

### 3. **Bulk Assignment**
- View all employees in a table
- Select department for each employee from dropdown
- Save all changes at once
- Track changes before saving (highlighted in yellow)

### 4. **Filtering**
Filter employees by:
- **Department** - Show only employees in a specific department
- **Status** - Assigned, Unassigned, or Linked to User
- **Search** - Search by employee name, user name, or designation

### 5. **Create Departments**
- Click "Create Department" button
- Enter department name
- Department is immediately available for assignment

## How to Use

### Assign Single Employee
1. Find the employee in the table
2. Select their department from the dropdown
3. Click "Save All Changes"

### Bulk Assign Multiple Employees
1. Use filters to narrow down employees
2. Select department for each employee you want to assign
3. Rows will highlight in yellow to show pending changes
4. Click "Save All Changes"
5. Confirm the action

### Create a New Department
1. Click "Create Department" button
2. Enter the department name (e.g., "Sales", "Engineering", "Support")
3. Click "Create"
4. Department is now available in all dropdowns

### Find Unassigned Employees
1. Set Status filter to "Unassigned"
2. Assign them to appropriate departments
3. Save changes

## Important Notes

### Employee-User Linking
- Employees need to be linked to Users to appear in Team Opportunities
- Look for the green checkmark badge in the "User" column
- If an employee doesn't have a user linked, you need to:
  1. Go to HR > Employee
  2. Open the employee record
  3. Set the "User ID" field
  4. Save

### Department = Team
- In this system, **Department** and **Team** are the same thing
- The Team Opportunities page groups by Department
- If an employee has no department, they won't appear in any team view

### Permissions
This page is accessible to:
- System Manager
- HR Manager

## Workflow Example

### Setting up a Sales Team
1. **Create the Department** (if it doesn't exist)
   - Click "Create Department"
   - Enter "Sales"
   - Click Create

2. **Assign Employees**
   - Find all sales employees
   - Select "Sales" from the department dropdown for each
   - Click "Save All Changes"

3. **Verify**
   - Go to Team Opportunities page
   - Filter by "Sales" team
   - You should now see all opportunities assigned to Sales team members

## Troubleshooting

### Employees not showing in Team Opportunities?
**Check:**
1. Employee has a User ID linked
2. Employee has a Department assigned
3. Employee's user has active ToDos for opportunities
4. Employee status is "Active"

### Department not appearing in dropdown?
**Solution:**
- Use "Create Department" button to create it
- Or go to HR > Department and create it manually
- Refresh the page after creating

### Changes not saving?
**Verify:**
1. You clicked "Save All Changes" button
2. You have proper permissions (System Manager or HR Manager)
3. Check browser console for errors
4. Check Frappe error logs

## API Methods

For developers, these API methods are available:

### `get_employees_with_teams()`
Returns all active employees with their team assignments.

### `get_all_departments()`
Returns list of all departments in the system.

### `assign_employee_to_team(employee, department)`
Assign a single employee to a department.

### `bulk_assign_employees(assignments)`
Bulk assign multiple employees to departments.

**Example:**
```python
frappe.call({
    method: 'opportunity_management.opportunity_management.page.employee_team_assignment.employee_team_assignment.bulk_assign_employees',
    args: {
        assignments: JSON.stringify([
            {employee: 'EMP-00001', department: 'Sales'},
            {employee: 'EMP-00002', department: 'Engineering'}
        ])
    }
})
```

### `create_department(department_name)`
Create a new department.

### `get_employee_stats()`
Get statistics about employee team assignments.

## Best Practices

1. **Keep Departments Organized**
   - Use clear, consistent naming (e.g., "Sales", not "sales team")
   - Don't create duplicate departments with different names

2. **Regular Maintenance**
   - Review unassigned employees regularly
   - Update team assignments when employees change roles

3. **Link Users**
   - Always link employees to their Frappe user accounts
   - This enables opportunity tracking and notifications

4. **Use Filters**
   - Use filters to focus on specific groups
   - Makes bulk assignments easier and faster

5. **Verify After Changes**
   - After bulk assignments, check Team Opportunities page
   - Ensure employees appear in the correct teams

## Integration with Other Features

### Team Opportunities Page
- Uses Department field to group opportunities
- Shows all opportunities assigned to team members
- Filters by department/team

### Calendar View
- Can filter by Responsible Engineer
- Engineers should have departments assigned for team tracking

### KPI Dashboard
- Team metrics are based on department assignments
- Proper team assignment ensures accurate KPIs

---

## Support

For issues:
1. Check Frappe logs: `bench --site [site] watch`
2. Check browser console for JavaScript errors
3. Verify permissions and employee data
