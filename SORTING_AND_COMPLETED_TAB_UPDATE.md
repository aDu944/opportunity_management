# Sorting and Completed Opportunities Tab Update

## Overview

This update adds three major features to both **My Opportunities** and **Team Opportunities** pages:

1. **Column Sorting** - Click any column header to sort (with visual indicators ▲▼⇅)
2. **Completed Opportunities Tab** - View closed/lost/converted opportunities separately
3. **Fixed "All Teams" Filter** - Now properly shows all teams in Team Opportunities page

---

## What's New

### 1. Column Sorting

**Both My Opportunities and Team Opportunities now support sorting by:**
- Urgency (overdue → due today → critical → high → medium → low)
- Opportunity Name (alphabetical)
- Customer Name (alphabetical)
- Status (for completed tab)
- Closing Date (chronological)
- Days Remaining (numerical)

**How to use:**
1. Click any column header to sort by that column (ascending)
2. Click the same header again to reverse the sort order (descending)
3. Visual indicators show current sort:
   - ▲ = Ascending
   - ▼ = Descending
   - ⇅ = Not currently sorted by this column

---

### 2. Completed Opportunities Tab

**New tab system in both pages:**
- **Open Opportunities** (default) - Shows active opportunities
- **Completed Opportunities** - Shows Closed/Lost/Converted opportunities

**Summary cards adapt to the active tab:**

**Open Tab:**
- Total Open
- Overdue (red)
- Due Today (orange)
- Due Tomorrow (yellow)

**Completed Tab:**
- Total Completed
- Converted (green)
- Closed (blue)
- Lost (gray)

---

### 3. Fixed "All Teams" Filter

**Before:** Could not switch back to "All Teams" after selecting a specific department

**After:** "All Teams" option works properly - shows opportunities from all departments

---

## Files Modified

### Frontend Changes

#### 1. `my_opportunities.js`

**Added:**
- Tab system with "Open" and "Completed" buttons
- `page.current_tab` state tracking
- `page.sort_by` and `page.sort_order` for sorting
- `sort_my_opportunities()` function for column sorting
- `getStatusBadge()` helper for completed status badges
- `window.sort_my_opportunities_handler()` global handler
- Summary cards that change based on active tab
- Status column for completed opportunities

**Modified:**
- `load_opportunities()` now passes `include_completed` parameter
- `render_summary()` shows different metrics for open vs completed
- `render_opportunities()` shows sortable headers and adapts to tab
- Urgency filter now hidden when viewing completed tab

---

#### 2. `team_opportunities.js`

**Added:**
- Tab system with "Open" and "Completed" buttons
- `page.current_tab` state tracking
- `page.sort_by` and `page.sort_order` for sorting
- `sort_opportunities()` function for column sorting
- `getStatusBadge()` helper for completed status badges
- `window.sort_opportunities_handler()` global handler
- Summary cards that change based on active tab
- Status column showing "Quotation Sent" vs "Pending"

**Modified:**
- `load_team_opportunities()` now passes `include_completed` parameter
- Fixed "All Teams" filter logic (passes `null` instead of empty string)
- `render_team_summary()` shows different metrics for open vs completed
- `render_team_opportunities()` shows sortable headers and adapts to tab
- Actions column only shown for open opportunities

---

### Backend Changes

#### 3. `api.py`

**Modified `get_my_opportunities()`:**
```python
def get_my_opportunities(user=None, include_completed=False):
```

**Changes:**
- Added `include_completed` parameter (default: False)
- ToDo filter now conditional:
  - Open opportunities: only open ToDos
  - Completed opportunities: all ToDos
- Opportunity filtering:
  - `include_completed=False`: skip Closed/Lost/Converted
  - `include_completed=True`: ONLY show Closed/Lost/Converted
- Urgency calculation:
  - Completed opportunities: urgency = "completed"
  - Open opportunities: existing urgency logic
- Added `"status": opp.status` to response for completed tab

---

**Modified `get_team_opportunities()`:**
```python
def get_team_opportunities(team=None, include_completed=False):
```

**Changes:**
- Added `include_completed` parameter (default: False)
- ToDo filter now conditional:
  - Open opportunities: only open ToDos
  - Completed opportunities: all ToDos
- Opportunity filtering:
  - `include_completed=False`: skip Closed/Lost/Converted
  - `include_completed=True`: ONLY show Closed/Lost/Converted
- Urgency calculation:
  - Completed opportunities: urgency = "completed"
  - Open opportunities: existing urgency logic

---

## How It Works

### Tab Switching Flow

**User clicks "Completed Opportunities" button:**

1. Frontend sets `page.current_tab = 'completed'`
2. Updates button styling (active tab = primary blue)
3. Hides urgency filter (only for open tab)
4. Calls backend API:
   ```javascript
   frappe.call({
       method: 'get_my_opportunities', // or get_team_opportunities
       args: {
           include_completed: true
       }
   });
   ```
5. Backend filters for ONLY Closed/Lost/Converted opportunities
6. Frontend renders:
   - Completed summary cards (Converted/Closed/Lost counts)
   - Status column instead of urgency
   - Status badges (green ✓ Converted, blue Closed, gray Lost)
   - No "Actions" column (can't create quotations)

---

### Sorting Flow

**User clicks "Customer" column header:**

1. Frontend handler `window.sort_my_opportunities_handler('customer')` is called
2. Checks if already sorted by 'customer':
   - If yes: toggle sort order (asc ↔ desc)
   - If no: set sort_by = 'customer', sort_order = 'asc'
3. Sort the `page.opportunities` array:
   ```javascript
   page.opportunities.sort((a, b) => {
       const aVal = a.customer || '';
       const bVal = b.customer || '';
       if (aVal < bVal) return page.sort_order === 'asc' ? -1 : 1;
       if (aVal > bVal) return page.sort_order === 'asc' ? 1 : -1;
       return 0;
   });
   ```
4. Re-render the table with updated sort indicators:
   - Customer column shows ▲ or ▼
   - Other columns show ⇅

---

## Usage Examples

### Example 1: View Completed Opportunities

**My Opportunities page:**
1. Open "My Opportunities" page
2. Click "Completed Opportunities" button
3. See all your closed/lost/converted opportunities
4. Summary shows: Total Completed, Converted, Closed, Lost
5. Table shows status badges instead of urgency

---

### Example 2: Sort by Most Overdue

**Team Opportunities page:**
1. Open "Team Opportunities" page
2. Ensure "Open Opportunities" tab is active
3. Click "Days Left" column header once (ascending)
4. Negative numbers (overdue) appear at the top
5. Click again to reverse (descending) - future dates at top

---

### Example 3: Filter All Teams

**Team Opportunities page:**
1. Open "Team Opportunities" page
2. Select a specific department (e.g., "Sales")
3. See only Sales opportunities
4. Change filter to "All Teams"
5. Now see opportunities from all departments

---

## Testing

### Test Case 1: Tab Switching

**Steps:**
1. Go to My Opportunities
2. Click "Completed Opportunities" tab
3. Verify only Closed/Lost/Converted opportunities appear
4. Verify summary cards show Converted/Closed/Lost counts
5. Click "Open Opportunities" tab
6. Verify only open opportunities appear
7. Verify summary cards show Overdue/Due Today/Due Tomorrow

**Expected:** Tabs work correctly, data updates, summaries change

---

### Test Case 2: Column Sorting

**Steps:**
1. Go to Team Opportunities
2. Click "Urgency" column header
3. Verify overdue opportunities appear first (ascending)
4. Verify ▲ indicator appears next to "Urgency"
5. Click "Urgency" again
6. Verify low urgency opportunities appear first (descending)
7. Verify ▼ indicator appears
8. Click "Customer" column
9. Verify sorted alphabetically by customer name
10. Verify ▲ appears next to "Customer", ⇅ next to "Urgency"

**Expected:** Sorting works for all columns, indicators update correctly

---

### Test Case 3: All Teams Filter

**Steps:**
1. Go to Team Opportunities
2. Verify default selection is your department
3. Change to "All Teams"
4. Verify you see opportunities from multiple departments
5. Change to specific department (e.g., "Engineering")
6. Verify only Engineering opportunities shown
7. Change back to "All Teams"
8. Verify all opportunities visible again

**Expected:** Filter works in all directions, no errors

---

## Troubleshooting

### Problem: "All Teams" Not Working

**Symptom:** Selecting "All Teams" shows no opportunities

**Solution:**
The issue was in the filter logic. Now fixed:
```javascript
// OLD (broken)
const team = page.fields_dict.team_filter.get_value();

// NEW (works)
const team = (team_value && team_value !== 'All Teams' && team_value !== 'Loading...')
    ? team_value : null;
```

When `team` is `null`, the backend shows all teams.

---

### Problem: Sort Not Working After Tab Switch

**Symptom:** Sorting doesn't work after switching tabs

**Solution:**
Make sure to reset `page.opportunities` when loading data:
```javascript
callback: function(r) {
    if (r.message) {
        page.opportunities = r.message;  // Reset the array
        render_summary(page);
        render_opportunities(page);
    }
}
```

---

### Problem: Completed Tab Shows Open Opportunities

**Symptom:** Completed tab shows opportunities that aren't closed

**Solution:**
Check the backend filter logic:
```python
if include_completed:
    # Only show completed opportunities
    if opp.status not in ["Closed", "Lost", "Converted"]:
        continue
else:
    # Skip closed/lost/converted opportunities
    if opp.status in ["Closed", "Lost", "Converted"]:
        continue
```

Make sure the condition is `not in` for completed tab.

---

### Problem: Sort Indicators Not Updating

**Symptom:** Visual indicators (▲▼⇅) don't change when clicking headers

**Solution:**
Ensure `getSortIcon()` is using the page state:
```javascript
const getSortIcon = (column) => {
    if (page.sort_by === column) {
        return page.sort_order === 'asc' ? ' ▲' : ' ▼';
    }
    return ' ⇅';
};
```

And that you're re-rendering after sorting:
```javascript
function sort_opportunities(page, column) {
    // ... sorting logic ...
    render_opportunities(page);  // Re-render to update icons
}
```

---

## Summary of Changes

### Features Added:
✅ Column sorting for all opportunity tables
✅ Completed opportunities tab in both pages
✅ Fixed "All Teams" filter in Team Opportunities
✅ Visual sort indicators (▲▼⇅)
✅ Status badges for completed opportunities
✅ Adaptive summary cards based on tab
✅ Status column for completed tab

### Backend Changes:
✅ `get_my_opportunities(include_completed=False)` parameter
✅ `get_team_opportunities(include_completed=False)` parameter
✅ Conditional ToDo filtering based on completion status
✅ Urgency calculation for completed opportunities
✅ Added `status` field to API responses

### Frontend Changes:
✅ Tab buttons with active state styling
✅ Sort state tracking (sort_by, sort_order)
✅ Global sort handlers for onclick events
✅ Conditional rendering based on active tab
✅ Helper functions for badges and sorting

---

## Next Steps

1. **Deploy to Frappe Cloud** - Push changes and deploy
2. **Test on production** - Verify all features work
3. **Train users** - Show how to use new tabs and sorting
4. **Monitor feedback** - Check if any issues arise

---

## Customization Options

### Option 1: Change Default Tab

To default to "Completed" tab instead of "Open":

**Edit:** `my_opportunities.js` or `team_opportunities.js`

**Change:**
```javascript
// FROM:
page.current_tab = 'open';

// TO:
page.current_tab = 'completed';
```

Also update the initial active tab styling:
```javascript
// FROM:
page.main.find('.tab-btn[data-tab="open"]').addClass('btn-primary')...

// TO:
page.main.find('.tab-btn[data-tab="completed"]').addClass('btn-primary')...
```

---

### Option 2: Add More Sort Columns

To add sorting for additional columns (e.g., "Items Count"):

**Edit:** `my_opportunities.js` or `team_opportunities.js`

**1. Add onclick handler to table header:**
```javascript
<th onclick="window.sort_my_opportunities_handler('items_count')">Items${getSortIcon('items_count')}</th>
```

**2. Add case to sort function:**
```javascript
switch(column) {
    // ... existing cases ...
    case 'items_count':
        aVal = a.items ? a.items.length : 0;
        bVal = b.items ? b.items.length : 0;
        break;
}
```

---

### Option 3: Change Sort Icons

To use different icons (e.g., arrows ↑↓ instead of triangles ▲▼):

**Edit:** `getSortIcon()` function

**Change:**
```javascript
const getSortIcon = (column) => {
    if (page.sort_by === column) {
        return page.sort_order === 'asc' ? ' ↑' : ' ↓';
    }
    return ' ↕';
};
```

---

**Questions or issues?** Check the troubleshooting section above!
