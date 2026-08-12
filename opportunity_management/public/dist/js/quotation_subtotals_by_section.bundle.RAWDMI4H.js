(()=>{frappe.ui.form.on("Quotation",{refresh:function(t){t.add_custom_button(__("Add Title Row"),function(){frappe.prompt([{label:"Section Title",fieldname:"title_text",fieldtype:"Data",reqd:1}],function(o){let e=t.add_child("items");e.custom_is_title_row=1,e.custom_title_text=o.title_text,e.description=o.title_text,e.item_code="TITLE-ROW",e.qty=1,e.rate=0,e.amount=0,t.refresh_field("items"),t.doc.custom_show_section_subtotals&&s(t),frappe.show_alert({message:"Title row added: "+o.title_text,indicator:"green"})},__("Add Section Title"),__("Add"))}),setTimeout(function(){c(t),t.doc.custom_show_section_subtotals&&s(t)},100)},custom_show_section_subtotals:function(t){t.doc.custom_show_section_subtotals?s(t):n(t),c(t)},validate:function(t){t.doc.custom_show_section_subtotals&&s(t)}});frappe.ui.form.on("Quotation Item",{custom_is_title_row:function(t,o,e){let i=locals[o][e];i.custom_is_title_row&&(frappe.model.set_value(o,e,"item_code","TITLE-ROW"),frappe.model.set_value(o,e,"qty",1),frappe.model.set_value(o,e,"rate",0),frappe.model.set_value(o,e,"amount",0),frappe.model.set_value(o,e,"description",i.custom_title_text||""))},custom_title_text:function(t,o,e){let i=locals[o][e];i.custom_is_title_row&&frappe.model.set_value(o,e,"description",i.custom_title_text)},amount:function(t,o,e){t.doc.custom_show_section_subtotals&&s(t)},items_remove:function(t){t.doc.custom_show_section_subtotals&&setTimeout(()=>s(t),100)}});function s(t){let o=[],e=null;t.doc.items.forEach((i,l)=>{i.custom_is_title_row?(e&&o.push(e),e={title:i.custom_title_text||"Untitled Section",title_row_idx:l,items:[],total:0}):e&&(e.items.push(i),e.total+=i.amount||0)}),e&&o.push(e),t.section_totals=o,c(t)}function n(t){t.section_totals=[],c(t)}function c(t){if(!document.getElementById("title-row-styles")){var o=document.createElement("style");o.id="title-row-styles",o.innerHTML=`
            .grid-row[data-is-title="1"] {
                background-color: #f0f4f7 !important;
                font-weight: bold;
            }
            .grid-row[data-is-title="1"] .grid-static-col[data-fieldname="description"] {
                font-size: 14px;
                color: #2c3e50;
            }
            .section-total {
                font-size: 12px;
                color: #5e64ff;
                font-weight: normal;
                float: right;
                margin-right: 20px;
            }
        `,document.head.appendChild(o)}t.fields_dict.items&&t.fields_dict.items.grid&&t.fields_dict.items.grid.wrapper.find(".grid-row").each(function(e){var i=$(this).attr("data-name"),l=locals["Quotation Item"][i];if(l&&l.custom_is_title_row&&($(this).attr("data-is-title","1"),t.doc.custom_show_section_subtotals&&t.section_totals)){let _=t.section_totals.find(a=>a.title_row_idx===e);if(_){let a=$(this).find('.grid-static-col[data-fieldname="description"]');a.find(".section-total").remove(),_.total>0&&a.append(`
                                <span class="section-total">
                                    Section Total: ${format_currency(_.total,t.doc.currency)}
                                </span>
                            `)}}})}})();
//# sourceMappingURL=quotation_subtotals_by_section.bundle.RAWDMI4H.js.map
