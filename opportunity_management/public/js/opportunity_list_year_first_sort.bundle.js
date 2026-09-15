// From ERPNext Client Script: Opportunity List Year-First Sort
// Doctype: Opportunity | View: List | Size: 1181 bytes
// Opportunity list view — sort by transaction_date desc, name desc (year-first ordering)
frappe.listview_settings['Opportunity'] = frappe.listview_settings['Opportunity'] || {};
const _opp_onload = frappe.listview_settings['Opportunity'].onload;
frappe.listview_settings['Opportunity'].onload = function(listview) {
    if (typeof _opp_onload === 'function') _opp_onload(listview);

    // Override list query order_by so multi-column sort sticks even when
    // user explicitly picks "ID" from the sort dropdown (the name suffix is
    // the year, so plain name-sort gives wrong year-order).
    const _get_args = listview.get_args.bind(listview);
    listview.get_args = function() {
        const args = _get_args();
        const sf = (this.sort_selector && this.sort_selector.sort_by) || 'modified';
        const so = (this.sort_selector && this.sort_selector.sort_order) || 'desc';
        if (sf === 'name' || sf === 'transaction_date') {
            // Always year-then-sequence (transaction_date carries the year reliably)
            args.order_by = `\`tabOpportunity\`.transaction_date ${so}, \`tabOpportunity\`.name ${so}`;
        }
        return args;
    };
};
