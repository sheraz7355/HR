from datetime import datetime
from shared.extensions import db


PLACEHOLDER_HELP = {
    "company_name": "Company name",
    "company_address": "Company street address",
    "company_city": "Company city",
    "company_phone": "Company phone number",
    "company_email": "Company email",
    "company_tax_id": "Company tax/NTN number",
    "company_logo": "Company logo image tag",
    "invoice_no": "Invoice / voucher number",
    "invoice_date": "Invoice date",
    "due_date": "Payment due date",
    "status": "Invoice status (approved/unapproved)",
    "party_name": "Customer or supplier name",
    "party_address": "Customer or supplier address",
    "party_city": "Customer or supplier city",
    "party_phone": "Customer or supplier phone",
    "party_email": "Customer or supplier email",
    "party_tax_id": "Customer or supplier tax ID",
    "items_table": "Full HTML table of invoice line items",
    "subtotal": "Subtotal amount",
    "discount": "Total discount amount",
    "tax": "Total sales tax amount",
    "grand_total": "Net total payable/receivable",
    "delivery_charges": "Delivery charges (sales only)",
    "installation_charges": "Installation charges (sales only)",
    "commission": "Commission (procurement only)",
    "freight": "Freight charges (procurement only)",
    "loading_unloading": "Loading/unloading charges (procurement only)",
    "withholding_tax": "Withholding tax (procurement only)",
    "notes": "Invoice notes",
}


def render_invoice_template(body_html, ctx):
    """Replace {{placeholder}} tokens in body_html with values from ctx dict."""
    import html as html_mod
    for key, val in ctx.items():
        token = "{{" + key + "}}"
        if val is None:
            val = ""
        body_html = body_html.replace(token, str(val))
    return body_html


class InvoiceTemplate(db.Model):
    __tablename__ = "invoice_templates"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # "sales" or "purchase"
    body_html = db.Column(db.Text, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_default(cls, doc_type):
        t = cls.query.filter_by(type=doc_type, is_default=True).first()
        if t:
            return t
        return cls.query.filter_by(type=doc_type).order_by(cls.id).first()

    @classmethod
    def default_body(cls, doc_type):
        if doc_type == "sales":
            return (
                '<div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">\n'
                '  <div style="text-align: center; margin-bottom: 30px;">\n'
                '    {{company_logo}}\n'
                '    <h1 style="margin: 5px 0;">{{company_name}}</h1>\n'
                '    <p style="margin: 2px 0;">{{company_address}}, {{company_city}}</p>\n'
                '    <p style="margin: 2px 0;">Phone: {{company_phone}} | Email: {{company_email}}</p>\n'
                '    <p style="margin: 2px 0;">NTN: {{company_tax_id}}</p>\n'
                '  </div>\n'
                '  <hr style="border: 1px solid #e2e8f0;">\n'
                '  <h2 style="text-align: center; color: #0d9488;">SALES INVOICE</h2>\n'
                '  <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">\n'
                '    <tr>\n'
                '      <td style="width: 50%; vertical-align: top; padding: 5px;">\n'
                '        <strong>Bill To:</strong><br>\n'
                '        {{party_name}}<br>\n'
                '        {{party_address}}<br>\n'
                '        {{party_city}}<br>\n'
                '        Phone: {{party_phone}}<br>\n'
                '        Email: {{party_email}}<br>\n'
                '        NTN: {{party_tax_id}}\n'
                '      </td>\n'
                '      <td style="width: 50%; vertical-align: top; padding: 5px; text-align: right;">\n'
                '        <strong>Invoice #:</strong> {{invoice_no}}<br>\n'
                '        <strong>Date:</strong> {{invoice_date}}<br>\n'
                '        <strong>Due Date:</strong> {{due_date}}<br>\n'
                '        <strong>Status:</strong> {{status}}\n'
                '      </td>\n'
                '    </tr>\n'
                '  </table>\n'
                '  {{items_table}}\n'
                '  <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">\n'
                '    <tr><td style="text-align: right; padding: 5px; width: 80%;"><strong>Subtotal:</strong></td><td style="text-align: right; padding: 5px; width: 20%;">{{subtotal}}</td></tr>\n'
                '    <tr><td style="text-align: right; padding: 5px;"><strong>Discount:</strong></td><td style="text-align: right; padding: 5px;">{{discount}}</td></tr>\n'
                '    <tr><td style="text-align: right; padding: 5px;"><strong>Sales Tax:</strong></td><td style="text-align: right; padding: 5px;">{{tax}}</td></tr>\n'
                '    <tr><td style="text-align: right; padding: 5px;"><strong>Delivery Charges:</strong></td><td style="text-align: right; padding: 5px;">{{delivery_charges}}</td></tr>\n'
                '    <tr><td style="text-align: right; padding: 5px;"><strong>Installation Charges:</strong></td><td style="text-align: right; padding: 5px;">{{installation_charges}}</td></tr>\n'
                '    <tr style="font-weight: 700; font-size: 16px; border-top: 2px solid #0d9488;"><td style="text-align: right; padding: 5px;">Net Receivable:</td><td style="text-align: right; padding: 5px;">{{grand_total}}</td></tr>\n'
                '  </table>\n'
                '  <div style="margin-top: 20px; padding: 10px; border-top: 1px solid #e2e8f0; font-size: 12px;">\n'
                '    <p>{{notes}}</p>\n'
                '  </div>\n'
                '</div>'
            )
        return (
            '<div style="font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px;">\n'
            '  <div style="text-align: center; margin-bottom: 30px;">\n'
            '    {{company_logo}}\n'
            '    <h1 style="margin: 5px 0;">{{company_name}}</h1>\n'
            '    <p style="margin: 2px 0;">{{company_address}}, {{company_city}}</p>\n'
            '    <p style="margin: 2px 0;">Phone: {{company_phone}} | Email: {{company_email}}</p>\n'
            '    <p style="margin: 2px 0;">NTN: {{company_tax_id}}</p>\n'
            '  </div>\n'
            '  <hr style="border: 1px solid #e2e8f0;">\n'
            '  <h2 style="text-align: center; color: #7c3aed;">PURCHASE INVOICE</h2>\n'
            '  <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">\n'
            '    <tr>\n'
            '      <td style="width: 50%; vertical-align: top; padding: 5px;">\n'
            '        <strong>From:</strong><br>\n'
            '        {{party_name}}<br>\n'
            '        {{party_address}}<br>\n'
            '        {{party_city}}<br>\n'
            '        Phone: {{party_phone}}<br>\n'
            '        Email: {{party_email}}<br>\n'
            '        NTN: {{party_tax_id}}\n'
            '      </td>\n'
            '      <td style="width: 50%; vertical-align: top; padding: 5px; text-align: right;">\n'
            '        <strong>Invoice #:</strong> {{invoice_no}}<br>\n'
            '        <strong>Date:</strong> {{invoice_date}}<br>\n'
            '        <strong>Due Date:</strong> {{due_date}}<br>\n'
            '        <strong>Status:</strong> {{status}}\n'
            '      </td>\n'
            '    </tr>\n'
            '  </table>\n'
            '  {{items_table}}\n'
            '  <table style="width: 100%; border-collapse: collapse; margin-top: 20px;">\n'
            '    <tr><td style="text-align: right; padding: 5px; width: 80%;"><strong>Subtotal:</strong></td><td style="text-align: right; padding: 5px; width: 20%;">{{subtotal}}</td></tr>\n'
            '    <tr><td style="text-align: right; padding: 5px;"><strong>Discount:</strong></td><td style="text-align: right; padding: 5px;">{{discount}}</td></tr>\n'
            '    <tr><td style="text-align: right; padding: 5px;"><strong>Sales Tax:</strong></td><td style="text-align: right; padding: 5px;">{{tax}}</td></tr>\n'
            '    <tr><td style="text-align: right; padding: 5px;"><strong>Commission:</strong></td><td style="text-align: right; padding: 5px;">{{commission}}</td></tr>\n'
            '    <tr><td style="text-align: right; padding: 5px;"><strong>Freight:</strong></td><td style="text-align: right; padding: 5px;">{{freight}}</td></tr>\n'
            '    <tr><td style="text-align: right; padding: 5px;"><strong>Loading/Unloading:</strong></td><td style="text-align: right; padding: 5px;">{{loading_unloading}}</td></tr>\n'
            '    <tr><td style="text-align: right; padding: 5px;"><strong>Withholding Tax:</strong></td><td style="text-align: right; padding: 5px;">{{withholding_tax}}</td></tr>\n'
            '    <tr style="font-weight: 700; font-size: 16px; border-top: 2px solid #7c3aed;"><td style="text-align: right; padding: 5px;">Net Payable:</td><td style="text-align: right; padding: 5px;">{{grand_total}}</td></tr>\n'
            '  </table>\n'
            '  <div style="margin-top: 20px; padding: 10px; border-top: 1px solid #e2e8f0; font-size: 12px;">\n'
            '    <p>{{notes}}</p>\n'
            '  </div>\n'
            '</div>'
        )
