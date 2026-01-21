# Opportunity Management - New Features

## 1. Auto-Close Functionality

### What it does:
When a Quotation is submitted, the system automatically:
- **Closes the linked Opportunity** (status changed to "Converted" or "Closed")
- **Closes all related ToDos** for that Opportunity
- **Updates the Opportunity Assignment Log** with completion details
- **Sends email notifications** to all assignees

### How it works:
The hook is configured in `hooks.py`:
```python
"Quotation": {
    "on_submit": "opportunity_management.quotation_handler.on_quotation_submit",
}
```

### Files modified:
- `opportunity_management/hooks.py` - Added Quotation submit hook
- `opportunity_management/quotation_handler.py` - Enhanced to close Opportunity status

### Testing:
1. Create an Opportunity
2. Assign it to a user (this creates ToDos)
3. Create a Quotation linked to the Opportunity
4. Submit the Quotation
5. Verify:
   - Opportunity status is "Converted" or "Closed"
   - All related ToDos are marked as "Closed"
   - Assignment log is updated
   - Email notifications sent to assignees

---

## 2. Calendar View Feature

### What it does:
Provides a visual calendar interface to:
- View all opportunities by their closing dates
- Color-coded by urgency level (Urgent=Red, High=Orange, Medium=Yellow, Low=Green)
- Filter by Status, Urgency, Owner, or Responsible Engineer
- Switch between Month, Week, and List views
- Click on opportunities to see details or open the full record

### Access:
Navigate to: **Opportunity Management > Opportunity Calendar**

Or directly: `/app/opportunity-calendar`

### Features:
1. **Multiple Views:**
   - Month view (default)
   - Week view
   - List view

2. **Filters:**
   - Status (Open, Quotation, Converted, Lost, etc.)
   - Urgency Level (Urgent, High, Medium, Low)
   - Opportunity Owner
   - Responsible Engineer

3. **Color Coding:**
   - 🔴 Red = Urgent
   - 🟠 Orange = High
   - 🟡 Yellow = Medium
   - 🟢 Green = Low

4. **Interactive:**
   - Hover over events to see quick details
   - Click events to open detailed dialog
   - "Open Opportunity" button to navigate to full record
   - "New Opportunity" button to create new records

### Files created:
- `opportunity_management/opportunity_management/page/opportunity_calendar/`
  - `opportunity_calendar.json` - Page configuration
  - `opportunity_calendar.py` - Backend API methods
  - `opportunity_calendar.js` - Frontend calendar implementation

### API Methods:

#### `get_calendar_events(start, end, filters=None)`
Fetches opportunities for the calendar view.

**Parameters:**
- `start` (date): Start date for the range
- `end` (date): End date for the range
- `filters` (dict): Optional filters (status, owner, urgency, etc.)

**Returns:** List of calendar events in FullCalendar format

#### `get_filter_options()`
Returns available filter options (owners, engineers, statuses, urgency levels).

### Installation:
After pulling these changes:

1. **Migrate the database:**
   ```bash
   bench --site [your-site] migrate
   ```

2. **Clear cache:**
   ```bash
   bench --site [your-site] clear-cache
   ```

3. **Build assets:**
   ```bash
   bench build
   ```

4. **Restart bench:**
   ```bash
   bench restart
   ```

### Permissions:
The calendar page is accessible to:
- System Manager
- Sales Manager
- Sales User

To add more roles, edit:
`opportunity_management/opportunity_management/page/opportunity_calendar/opportunity_calendar.json`

### Customization:

#### Change color scheme:
Edit the `get_urgency_color()` function in `opportunity_calendar.py`:
```python
color_map = {
    "Urgent": "#your-color",
    "High": "#your-color",
    # ... etc
}
```

#### Add more filters:
1. Add field in `create_filters()` method in `opportunity_calendar.js`
2. Update `get_calendar_events()` in `opportunity_calendar.py` to handle the new filter

#### Change date field:
Currently uses `custom_closing_date` (falls back to `transaction_date`). To change:
- Edit the query in `get_calendar_events()` in `opportunity_calendar.py`

---

## Dependencies

Both features require:
- Frappe Framework (v14+)
- ERPNext
- FullCalendar library (bundled with Frappe)

---

## Support

For issues or questions:
1. Check the Frappe logs: `bench --site [site] watch`
2. Review browser console for JavaScript errors
3. Check Python traceback in Error Log doctype
