import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

DT = 'Sales Order Item'

def run():
    def ps(field, prop, value, prop_type='Check'):
        make_property_setter(DT, field, prop, value, prop_type,
            for_doctype=False, validate_fields_for_doctype=False)

    for f, cols in {'description': 3, 'qty': 1, 'uom': 1, 'rate': 1, 'amount': 2}.items():
        ps(f, 'in_list_view', 1, 'Check')
        ps(f, 'columns', cols, 'Int')

    for f in ['item_code', 'delivery_date', 'warehouse']:
        ps(f, 'in_list_view', 0, 'Check')

    for f, cols in {'custom_manufacturer': 1, 'custom_part_number': 1}.items():
        frappe.db.set_value('Custom Field', {'dt': DT, 'fieldname': f}, {'in_list_view': 1, 'columns': cols})

    for f in ['custom_sn_po','custom_print_label','custom_festo_type_code','custom_lead_time_weeks',
              'custom_incoterm','custom_planned_order_date','custom_origin','custom_transit_days',
              'custom_tech_desc','custom_order_urgency','custom_po_number']:
        frappe.db.set_value('Custom Field', {'dt': DT, 'fieldname': f}, {'in_list_view': 0})

    frappe.db.commit()
    frappe.clear_cache(doctype=DT)
    print('OK')
