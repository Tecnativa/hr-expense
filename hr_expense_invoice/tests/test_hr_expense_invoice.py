# Copyright 2017 Tecnativa - Vicent Cubells
# Copyright 2021 Tecnativa - Pedro M. Baeza
# Copyright 2021-2023 Tecnativa - Víctor Martínez
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl.html).
import base64

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger

from odoo.addons.hr_expense.tests.common import TestExpenseCommon


@tagged("post_install", "-at_install")
class TestHrExpenseInvoice(TestExpenseCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cash_journal = cls.company_data["default_journal_cash"]
        cls.company_data["company"].account_sale_tax_id = False
        cls.company_data["company"].account_purchase_tax_id = False
        cls.product_a.supplier_taxes_id = False
        cls.product_b.supplier_taxes_id = False
        cls.invoice = cls.init_invoice(
            "in_invoice",
            products=[cls.product_a],
        )
        cls.invoice.invoice_line_ids.price_unit = 100
        cls.invoice2 = cls.invoice.copy(
            {
                "invoice_date": fields.Date.today(),
            }
        )
        cls.expense = cls.create_expenses(
            {
                "name": "Expense 1 Paid by Employee",
                "employee_id": cls.expense_employee.id,
                "product_id": cls.product_a.id,
                "payment_mode": "own_account",
                "total_amount_currency": 100.0,
                "company_id": cls.company_data["company"].id,
            }
        )
        cls.expense2 = cls.create_expenses(
            {
                "name": "Expense 2 Paid by Company",
                "employee_id": cls.expense_employee.id,
                "product_id": cls.product_a.id,
                "payment_mode": "company_account",
                "total_amount_currency": 100.0,
                "company_id": cls.company_data["company"].id,
            }
        )
        cls._create_attachment(cls.expense)
        cls._create_attachment(cls.expense2)

    def _expense_register_payment(self, expense):
        in_payment_state = expense.account_move_id._get_invoice_in_payment_state()
        payment = self.get_new_payment(expense, expense.total_amount)
        self.assertEqual(expense.state, in_payment_state)
        return payment

    def _transfer_move_register_payment(self, expense):
        to_pay_lines = expense.transfer_move_ids.line_ids.filtered_domain(
            [
                ("partner_id", "=", self.expense_employee.work_contact_id.id),
            ]
        )
        payment_register = (
            self.env["account.payment.register"]
            .with_context(
                active_model="account.move", active_ids=expense.transfer_move_ids.ids
            )
            .create(
                {
                    "amount": sum(to_pay_lines.mapped("credit")),
                    "journal_id": self.company_data["default_journal_bank"].id,
                    "payment_method_line_id": self.inbound_payment_method_line.id,
                }
            )
        )
        return payment_register._create_payments()

    @classmethod
    def _create_attachment(cls, expense):
        res_model, res_id = expense._name, expense.id
        return cls.env["ir.attachment"].create(
            {
                "name": f"Test attachment {res_id} ({res_model})",
                "res_model": res_model,
                "res_id": res_id,
                "datas": base64.b64encode(b"\xff data"),
            }
        )

    def _action_submit_expenses(self, expenses):
        expenses.action_submit()
        expenses._do_approve(check=False)

    def test_0_hr_tests_misc(self):
        self.assertEqual(self.expense.nb_attachment, 1)
        self.assertEqual(self.expense2.nb_attachment, 1)

    def test_1_hr_test_no_invoice(self):
        # We add an expense
        self.assertAlmostEqual(self.expense.total_amount_currency, 100.0)
        # Change product, check price changed
        self.expense.product_id = self.product_a
        self.assertAlmostEqual(
            self.expense.total_amount_currency, self.product_a.standard_price
        )
        # We approve expense, no invoice
        self._action_submit_expenses(self.expense)
        self.assertFalse(self.expense.invoice_id)
        # We post journal entries
        self.post_expenses_with_wizard(self.expense)
        self.assertEqual(self.expense.account_move_id.state, "posted")
        self.assertEqual(self.expense.account_move_id.payment_state, "not_paid")
        self.assertEqual(self.expense.state, "posted")
        # We make payment on invoice
        self._expense_register_payment(self.expense)

    @mute_logger("odoo.models.unlink")
    def test_2_hr_test_invoice(self):
        # We add an expense
        self.expense.total_amount_currency = 50
        self._action_submit_expenses(self.expense)
        # We add invoice to expense
        self.invoice.action_post()  # residual = 100
        self.assertEqual(self.invoice.amount_total, 100.0)
        with Form(self.expense) as f:
            f.invoice_id = self.invoice
        self.assertTrue(self.expense.invoice_id)
        # Adding the invoice, changes the total amount
        self.assertEqual(self.expense.total_amount, self.invoice.amount_total)
        # Test error when invoice is not posted
        self.expense.invoice_id.button_draft()
        # with self.assertRaises(UserError):
        #     self.expense.action_post()
        self.expense.invoice_id.action_post()
        # We post journal entries (transfer)
        self.expense.action_post()
        # self.assertEqual(self.expense.state, "in_payment")
        self.assertEqual(self.expense.invoice_id.payment_state, "paid")
        self.assertTrue(self.expense.transfer_move_ids)
        # Pay the transferred amount (through a hack using reversal)
        payment = self._transfer_move_register_payment(self.expense)
        for transfer_line in self.expense.transfer_move_ids.line_ids:
            self.assertTrue(transfer_line.reconciled)
        # self.assertEqual(self.expense.state, "paid")
        # Delete the payment
        payment.action_draft()
        payment.unlink()
        # self.assertEqual(self.expense.state, "in_payment")

    @mute_logger("odoo.models.unlink")
    def test_3_hr_test_create_invoice(self):
        # We add an expense
        self._action_submit_expenses(self.expense)
        self.assertFalse(self.expense.invoice_id)
        # We create an invoice from the expense
        self.expense.action_expense_create_invoice()
        self.assertTrue(self.expense.invoice_id)
        self.assertEqual(self.expense.invoice_id.state, "draft")
        self.assertRecordValues(
            self.expense.invoice_id.attachment_ids,
            [
                {"name": f"Test attachment {self.expense.id} (hr.expense)"},
            ],
        )
        self.expense.invoice_id.partner_id = self.partner_a
        self.expense.invoice_id.action_post()
        # self.assertEqual(self.expense.state, "approved")
        self.expense.action_post()
        # self.assertEqual(self.expense.state, "in_payment")
        self.assertEqual(self.expense.invoice_id.payment_state, "paid")
        self.assertTrue(self.expense.transfer_move_ids)
        # Pay the transferred amount
        payment = self._transfer_move_register_payment(self.expense)
        for transfer_line in self.expense.transfer_move_ids.line_ids:
            self.assertTrue(transfer_line.reconciled)
        # self.assertEqual(self.expense.state, "paid")
        # Delete the payment
        payment.action_draft()
        payment.unlink()
        # self.assertEqual(self.expense.state, "in_payment")

    def test_4_hr_test_invoice_paid_by_company(self):
        # We add an expense
        self._action_submit_expenses(self.expense2)
        # Vendor is required in order to create an invoice
        with self.assertRaises(UserError):
            self.expense2.action_expense_create_invoice()
        # Set Vendor
        self.expense2.vendor_id = self.partner_a
        # We create an invoice from the expense
        self.expense2.action_expense_create_invoice()
        self.assertTrue(self.expense2.invoice_id)
        # Invoice is created in posted state
        self.assertEqual(self.expense2.invoice_id.state, "posted")
