// PO status colorizer — covers both LIST view (MutationObserver on cells)
// and FORM view (frappe.ui.form.on refresh → frm.set_indicator).
// Loaded via app_include_js so it runs on every desk page.

(function() {
    console.log('[ALKHORA] po_list_extend loaded at', new Date().toISOString());

    // fg color + rgba tint for background
    const STYLES = {
        'Draft':                    { fg: '#8d99a6', bg: 'rgba(141,153,166,0.15)', ind: 'gray'   },
        'Open':                     { fg: '#6b7280', bg: 'rgba(107,114,128,0.15)', ind: 'gray'   },
        'In Progress':              { fg: '#8b5cf6', bg: 'rgba(139,92,246,0.15)',  ind: 'gray'   },
        'Received — Payment Due':   { fg: '#f97316', bg: 'rgba(249,115,22,0.15)',  ind: 'red'    },
        'Paid — Awaiting Delivery': { fg: '#0891b2', bg: 'rgba(8,145,178,0.15)',   ind: 'gray'   },
        'Shipped':                  { fg: '#eab308', bg: 'rgba(234,179,8,0.15)',   ind: 'gray'   },
        'On Hold':                  { fg: '#a16207', bg: 'rgba(161,98,7,0.15)',    ind: 'gray'   },
        'Closed':                   { fg: '#4b5563', bg: 'rgba(75,85,99,0.15)',    ind: 'gray'   },
        'Completed':                { fg: '#16a34a', bg: 'rgba(22,163,74,0.15)',   ind: 'green'  },
        'Cancelled':                { fg: '#dc2626', bg: 'rgba(220,38,38,0.15)',  ind: 'red'    },
    };

    // ─── LIST VIEW: DOM colorize ──────────────────────────────────────────
    function pillHtml(text, s) {
        return '<span style="display:inline-flex;align-items:center;gap:6px;' +
                    'padding:3px 10px;border-radius:12px;' +
                    'background:' + s.bg + ';color:' + s.fg + ';' +
                    'font-weight:500;font-size:11px;line-height:1.4;' +
                    'white-space:nowrap;">' +
                    '<span style="width:6px;height:6px;border-radius:50%;' +
                        'background:' + s.fg + ';display:inline-block;flex-shrink:0;">' +
                    '</span>' + text + '</span>';
    }
    function colorizeListCells() {
        document.querySelectorAll(
            '.list-row .list-row-col, .list-row-container .list-row-col'
        ).forEach(cell => {
            if (cell.dataset.alkhoraStyled === '1') return;
            const txt = (cell.textContent || '').trim();
            const s = STYLES[txt];
            if (!s) return;
            cell.dataset.alkhoraStyled = '1';
            cell.innerHTML = pillHtml(txt, s);
        });
    }
    function isPOListPage() {
        const r = (window.frappe && frappe.get_route) ? (frappe.get_route() || []) : [];
        return r[0] === 'List' && r[1] === 'Purchase Order';
    }
    let observer = null;
    function startListObserver() {
        if (observer) observer.disconnect();
        observer = new MutationObserver(() => {
            if (isPOListPage()) colorizeListCells();
        });
        observer.observe(document.body, {childList: true, subtree: true});
        setTimeout(colorizeListCells, 100);
        setTimeout(colorizeListCells, 500);
        setTimeout(colorizeListCells, 1500);
    }

    // ─── FORM VIEW: set indicator via frappe.ui.form.on ───────────────────
    function attachFormIndicator() {
        if (!(window.frappe && frappe.ui && frappe.ui.form)) return;
        frappe.ui.form.on('Purchase Order', {
            refresh: function(frm) {
                if (frm.doc.docstatus === undefined) return;
                const s = frm.doc.custom_delivery_payment_status;
                const style = STYLES[s];
                if (!style) return;

                const apply = () => {
                    // First call Frappe's native set_indicator so the pill
                    // element is guaranteed to exist in the header.
                    try { frm.page.set_indicator(s, style.ind); }
                    catch (e) {}
                    // Then find the pill and rewrite it with our hex-color
                    // inline styles so cyan/purple/orange render regardless
                    // of Frappe's palette.
                    try {
                        const pill = frm.page.wrapper && frm.page.wrapper.find
                            ? frm.page.wrapper.find('.indicator-pill').first()[0]
                            : document.querySelector('.page-head .indicator-pill');
                        if (pill) {
                            pill.style.background = style.bg;
                            pill.style.color = style.fg;
                            pill.style.fontWeight = '500';
                            // Recolor the ::before dot via class swap + inline
                            pill.style.setProperty('--indicator-dot-color', style.fg);
                            // The dot inside .indicator-pill uses a ::before
                            // pseudo — we can't restyle via inline; inject a
                            // dedicated <span> dot INSIDE the pill instead.
                            pill.innerHTML =
                                '<span style="width:6px;height:6px;border-radius:50%;' +
                                'background:' + style.fg + ';display:inline-block;' +
                                'margin-right:6px;vertical-align:middle;"></span>' + s;
                            pill.classList.add('alkhora-custom-pill');
                        }
                    } catch (e) {
                        console.warn('[ALKHORA] form pill restyle failed:', e);
                    }
                };
                apply();
                setTimeout(apply, 200);
                setTimeout(apply, 800);
            },
        });
    }

    // ─── Boot ─────────────────────────────────────────────────────────────
    function boot() {
        startListObserver();
        attachFormIndicator();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
    if (window.frappe && frappe.router && frappe.router.on) {
        frappe.router.on('change', function() {
            const r = frappe.get_route() || [];
            if (r[0] === 'List' && r[1] === 'Purchase Order') startListObserver();
        });
    }
})();
