(()=>{frappe.ui.form.on("Opportunity",{party_name:function(e){e.doc.party_name?frappe.db.get_value("Customer",e.doc.party_name,"custom_abr").then(a=>{a.message?e.set_value("custom_abr",a.message.custom_abr):e.set_value("custom_abr","")}):e.set_value("custom_abr","")}});})();
//# sourceMappingURL=opportunity_customer_abr.bundle.UJJJSWJG.js.map
