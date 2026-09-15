// From ERPNext Client Script: Alternative Items - Adjust Form Totals (Quotation)
// Doctype: Quotation | View: Form | Size: 2330 bytes

(function(){
    function recalc_alt(frm) {
        if (!frm || !frm.doc || !frm.doc.items) return;
        var alt_total = 0, alt_net = 0, alt_qty = 0;
        var cr = flt(frm.doc.conversion_rate || 1);
        (frm.doc.items || []).forEach(function(it) {
            if (it.custom_is_alternative) {
                alt_total += flt(it.amount);
                alt_net += flt(it.net_amount);
                alt_qty += flt(it.qty);
            }
        });
        if (alt_total === 0 && alt_qty === 0) return;

        frm.doc.total = flt(frm.doc.total) - alt_total;
        frm.doc.net_total = flt(frm.doc.net_total) - alt_net;
        frm.doc.grand_total = flt(frm.doc.grand_total) - alt_total;
        frm.doc.total_qty = flt(frm.doc.total_qty) - alt_qty;
        frm.doc.base_total = flt(frm.doc.base_total) - alt_total * cr;
        frm.doc.base_net_total = flt(frm.doc.base_net_total) - alt_net * cr;
        frm.doc.base_grand_total = flt(frm.doc.base_grand_total) - alt_total * cr;
        if (!frm.doc.disable_rounded_total) {
            frm.doc.rounded_total = frm.doc.grand_total;
            frm.doc.base_rounded_total = frm.doc.base_grand_total;
        }

        ['total','net_total','grand_total','rounded_total','total_qty',
         'base_total','base_net_total','base_grand_total','base_rounded_total'
        ].forEach(function(f){ frm.refresh_field(f); });
    }

    function debounced_recalc(frm) {
        setTimeout(function(){ recalc_alt(frm); }, 150);
    }

    ['Quotation','Sales Order','Sales Invoice'].forEach(function(dt) {
        frappe.ui.form.on(dt, {
            refresh: debounced_recalc,
            onload_post_render: debounced_recalc,
            validate: recalc_alt,
        });
    });

    ['Quotation Item','Sales Order Item','Sales Invoice Item'].forEach(function(cdt) {
        frappe.ui.form.on(cdt, {
            qty:                 function(frm){ debounced_recalc(frm); },
            rate:                function(frm){ debounced_recalc(frm); },
            amount:              function(frm){ debounced_recalc(frm); },
            net_amount:          function(frm){ debounced_recalc(frm); },
            custom_is_alternative:function(frm){ debounced_recalc(frm); },
            items_remove:        function(frm){ debounced_recalc(frm); },
        });
    });
})();
