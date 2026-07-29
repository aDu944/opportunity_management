# Controller for ESS Expense Category — a lightweight lookup DocType HR
# uses to constrain what expense types employees can pick from the mobile
# app. Consumers read via api.get_expense_categories which returns the
# categories with is_active=1.

from frappe.model.document import Document


class ESSExpenseCategory(Document):
    pass
