import frappe, json
def run():
    rows = frappe.db.sql("""
        select gl.voucher_no, gl.posting_date, gl.debit_in_account_currency as amt,
               left(gl.remarks,150) as remarks
        from `tabGL Entry` gl
        where gl.account like '33661%'
          and gl.is_cancelled = 0
          and gl.posting_date between '2025-01-01' and '2025-12-31'
          and (gl.remarks like '%صك%' or gl.remarks like '%cheque%' or gl.remarks like '%Cheque%'
               or gl.remarks like '%NBIQ%' or gl.remarks like '%clearing%' or gl.remarks like '%clearance%')
        order by gl.posting_date
    """, as_dict=True)
    open('/tmp/fee_je_dump.json','w').write(
        json.dumps([{'d':str(r.posting_date),'n':r.voucher_no,'a':float(r.amt),'r':r.remarks} for r in rows], ensure_ascii=False))
    print(f'wrote {len(rows)} rows')
