# Copyright 2019 Ecosoft <saranl@ecosoft.co.th>
# Copyright 2021 Tecnativa - Víctor Martínez
# Copyright 2024 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_expense_ids = fields.One2many(
        comodel_name="hr.expense", inverse_name="invoice_id", string="Expenses"
    )
    source_invoice_expense_id = fields.Many2one(
        comodel_name="hr.expense",
        help="Reference to the expense with a linked invoice that generated this"
        "transfer journal entry",
    )

    @api.constrains("amount_total")
    def _check_invoice_expense_ids(self):
        DecimalPrecision = self.env["decimal.precision"]
        precision = DecimalPrecision.precision_get("Product Price")
        for move in self.filtered("invoice_expense_ids"):
            expense_amount = sum(move.invoice_expense_ids.mapped("total_amount_currency"))
            if float_compare(expense_amount, move.amount_total, precision) != 0:
                raise ValidationError(
                    self.env._(
                        "You can't change the total amount, as there's an expense "
                        "linked to this invoice."
                    )
                )

    def action_open_expense_invoice(self):
        self.ensure_one()
        return self.invoice_expense_ids[:1].get_formview_action()

    # TODO: Revisar
    # def action_force_register_payment(self):
    #     if self.source_invoice_expense_id:
    #         return self.line_ids.action_register_payment()
    #     return super().action_force_register_payment()


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.constrains("account_id", "display_type")
    def _check_payable_receivable(self):
        _self = self.filtered("expense_id")
        return super(AccountMoveLine, (self - _self))._check_payable_receivable()
