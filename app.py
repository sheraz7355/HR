import os
import sys
import traceback as _tb

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, redirect, url_for, request
from flask_login import current_user
from werkzeug.exceptions import HTTPException


def _create_app():
    from shared.config import Config
    from shared.extensions import db, login_manager
    from shared.models.base import User, Role, Permission, load_user

    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        static_url_path="/static",
    )

    app.config.from_object(Config)

    import jinja2
    my_loader = jinja2.ChoiceLoader([
        app.jinja_loader,
        jinja2.FileSystemLoader([
            os.path.join(os.path.dirname(__file__), "hr_app", "templates"),
            os.path.join(os.path.dirname(__file__), "inventory_app", "templates"),
            os.path.join(os.path.dirname(__file__), "invoicing_app", "templates"),
            os.path.join(os.path.dirname(__file__), "finance_app", "templates"),
        ]),
    ])
    app.jinja_loader = my_loader

    db.init_app(app)
    login_manager.init_app(app)

    from shared.routes.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from shared.routes.admin_settings import admin_settings_bp
    app.register_blueprint(admin_settings_bp)

    from hr_app.app import register_hr_blueprints
    register_hr_blueprints(app)

    from inventory_app.app import register_inventory_blueprints
    register_inventory_blueprints(app)

    from invoicing_app.app import register_invoicing_blueprints
    register_invoicing_blueprints(app)

    from finance_app.app import register_finance_blueprints
    register_finance_blueprints(app)

    @app.context_processor
    def inject_now():
        return {"now": __import__("datetime").datetime.utcnow()}

    @app.context_processor
    def inject_company():
        # Company letterhead info for print headers on invoices/vouchers/forms.
        try:
            from shared.models.company_settings import CompanyInfo
            return {"company": CompanyInfo.get()}
        except Exception:
            return {"company": None}

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.hub"))
        return redirect(url_for("auth.login"))

    # DB init (lazy — runs on first request, not at import)
    @app.before_request
    def _init_db_once():
        if not getattr(app, "_db_initialized", False):
            app._db_initialized = True
            try:
                db.create_all()
                _seed_all_data(app)
            except Exception as e:
                print("DB INIT ERROR:", e)
                _tb.print_exc()

    def _friendly_error_page(code, title, message):
        return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{code} · {title}</title>
<style>
body{{font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
background:#f1f5f9;color:#1e293b;display:flex;align-items:center;justify-content:center;
min-height:100vh;margin:0}}
.box{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.06);
padding:40px 44px;max-width:440px;text-align:center}}
.code{{font-size:56px;font-weight:800;color:#2563eb;line-height:1;margin:0}}
h1{{font-size:20px;margin:12px 0 6px}}
p{{color:#64748b;font-size:14px;margin:0 0 22px}}
a{{display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:9px 20px;
border-radius:6px;font-size:14px;font-weight:600}}
a:hover{{background:#1d4ed8}}
</style></head><body><div class='box'>
<p class='code'>{code}</p><h1>{title}</h1><p>{message}</p>
<a href='/'>&larr; Back to dashboard</a></div></body></html>"""

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Proper pages for expected HTTP errors (404 missing record, 403 denied,
        # 405, etc.) instead of dumping a traceback — this is what made links to
        # deleted/forbidden records look like a crash.
        messages = {
            403: "You don't have permission to view this page.",
            404: "The page or record you're looking for doesn't exist.",
            405: "That action isn't allowed here.",
        }
        msg = messages.get(e.code, e.description or "Something went wrong.")
        return _friendly_error_page(e.code, e.name, msg), e.code

    @app.errorhandler(Exception)
    def handle_all(e):
        # Genuine unexpected server error — keep the traceback (useful while the
        # app is being stabilised) but only for real 500s, not HTTP errors.
        return f"<pre style='background:#fef2f2;padding:20px;border:2px solid #ef4444;border-radius:8px;font-size:13px;overflow:auto;max-height:90vh;'>{_tb.format_exc()}</pre>", 500

    return app


def _migrate_schema(db):
    """Idempotent, cross-dialect schema migrations.

    Each ALTER runs in its OWN autocommit transaction (``engine.begin()``) so a
    single failure can never roll back the others — the previous design shared
    one session, so one bad statement aborted the whole batch. This MUST run
    before any ORM query touches the affected tables, otherwise SQLAlchemy emits
    SELECTs listing model columns that do not yet exist (the production
    "column chart_of_accounts.level does not exist" 500s).
    """
    from sqlalchemy import inspect

    engine = db.engine
    is_pg = engine.dialect.name == "postgresql"
    # Postgres rejects `BOOLEAN DEFAULT 0` — it needs FALSE/TRUE literals.
    bool_false = "BOOLEAN DEFAULT FALSE" if is_pg else "BOOLEAN DEFAULT 0"
    bool_true = "BOOLEAN DEFAULT TRUE" if is_pg else "BOOLEAN DEFAULT 1"
    ts_type = "TIMESTAMP" if is_pg else "DATETIME"

    # (table, column, column_type_ddl)
    migrations = [
        ("chart_of_accounts", "level", "INTEGER DEFAULT 4"),
        ("chart_of_accounts", "is_fixed", bool_false),
        ("accounting_periods", "is_active", bool_true),
        ("users", "has_hr_access", bool_false),
        ("users", "has_inventory_access", bool_false),
        ("users", "has_invoicing_access", bool_false),
        ("users", "has_finance_access", bool_false),
        ("users", "has_accounting_access", bool_false),
        ("users", "login_id", "VARCHAR(120)"),
        ("consumption_vouchers", "charge_account_id", "INTEGER"),
        ("scrap_vouchers", "charge_account_id", "INTEGER"),
        ("inv_suppliers", "mobile", "VARCHAR(200) DEFAULT ''"),
        ("inv_suppliers", "tax_id", "VARCHAR(200) DEFAULT ''"),
        ("inv_suppliers", "payment_terms", "VARCHAR(200) DEFAULT ''"),
        ("inv_suppliers", "website", "VARCHAR(200) DEFAULT ''"),
        ("inv_suppliers", "notes", "VARCHAR(200) DEFAULT ''"),
        ("inv_customers", "contact_person", "VARCHAR(200) DEFAULT ''"),
        ("inv_customers", "mobile", "VARCHAR(200) DEFAULT ''"),
        ("inv_customers", "tax_id", "VARCHAR(200) DEFAULT ''"),
        ("inv_customers", "payment_terms", "VARCHAR(200) DEFAULT ''"),
        ("inv_customers", "website", "VARCHAR(200) DEFAULT ''"),
        ("inv_customers", "notes", "VARCHAR(200) DEFAULT ''"),
        ("inventory_settings", "purchase_flow", "VARCHAR(200) DEFAULT ''"),
        ("inventory_settings", "sales_flow", "VARCHAR(200) DEFAULT ''"),
        ("inv_invoices", "discount_mode", "VARCHAR(200) DEFAULT ''"),
        ("inv_invoices", "tax_mode", "VARCHAR(200) DEFAULT ''"),
        ("inv_invoices", "global_discount_pct", "FLOAT DEFAULT 0"),
        ("inv_invoices", "global_discount_value", "FLOAT DEFAULT 0"),
        ("inv_invoices", "global_sales_tax_pct", "FLOAT DEFAULT 0"),
        ("inv_invoices", "subtotal", "FLOAT DEFAULT 0"),
        ("inv_invoices", "total_discount", "FLOAT DEFAULT 0"),
        ("inv_invoices", "total_tax", "FLOAT DEFAULT 0"),
        ("inv_invoices", "notes", "VARCHAR(200) DEFAULT ''"),
        ("inv_invoices", "created_by", "INTEGER"),
        ("inv_invoices", "voucher_number", "VARCHAR(50) DEFAULT ''"),
        ("inv_invoices", "voucher_status", "VARCHAR(20) DEFAULT 'unapproved'"),
        ("inv_invoices", "payment_status", "VARCHAR(20) DEFAULT 'unpaid'"),
        ("inv_invoices", "charges_mode", "VARCHAR(20) DEFAULT 'general'"),
        ("inv_invoices", "total_charges", "FLOAT DEFAULT 0"),
        ("inv_invoices", "global_delivery", "FLOAT DEFAULT 0"),
        ("inv_invoices", "global_installation", "FLOAT DEFAULT 0"),
        ("inv_invoices", "approved_by", "INTEGER"),
        ("inv_invoices", "approved_at", ts_type),
        ("inv_invoice_items", "delivery", "FLOAT DEFAULT 0"),
        ("inv_invoice_items", "installation", "FLOAT DEFAULT 0"),
        ("inv_invoice_items", "comments", "TEXT"),
    ]

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, col, ddl in migrations:
        if table not in existing_tables:
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if col in cols:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        except Exception as e:
            print(f"MIGRATION SKIP {table}.{col}: {e}")

    # Unique index for invoice voucher numbers (best-effort).
    try:
        with engine.begin() as conn:
            conn.execute(db.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_inv_invoices_voucher_number "
                "ON inv_invoices(voucher_number)"
            ))
    except Exception as e:
        print("MIGRATION SKIP ix_inv_invoices_voucher_number:", e)


def _seed_all_data(app):
    with app.app_context():
        from shared.extensions import db
        from shared.models.base import User, Role, Permission
        from shared.models.ledger import ChartOfAccount
        from shared.models.stock_ledger import VoucherNumber, StockLedger
        from shared.models.inventory_settings import InventorySettings

        # Run schema migrations FIRST, before any ORM query, so model columns
        # added after the initial deploy are guaranteed to exist.
        _migrate_schema(db)

        Role.seed()
        admin_role = Role.query.filter_by(name=Role.ADMIN).first()
        mgr_role = Role.query.filter_by(name=Role.MANAGER).first()
        emp_role = Role.query.filter_by(name=Role.EMPLOYEE).first()

        for role, data in [(admin_role, [
            ("attendance", 1, 1, 1), ("leaves", 1, 1, 1),
            ("ess", 1, 1, 1), ("reports", 1, 1, 1),
            ("mss", 1, 1, 1), ("workplace", 1, 1, 1),
            ("timesheets", 1, 1, 1), ("digital_files", 1, 1, 1),
            ("compensation", 1, 1, 1), ("communications", 1, 1, 1),
            ("pf", 1, 1, 1), ("users", 1, 1, 1),
            ("products", 1, 1, 1), ("suppliers", 1, 1, 1),
            ("purchase_invoice", 1, 1, 1), ("purchase_return", 1, 1, 1),
            ("sales", 1, 1, 1), ("inventory", 1, 1, 1),
        ]), (mgr_role, [
            ("attendance", 1, 1, 0), ("leaves", 1, 1, 0),
            ("ess", 1, 1, 0), ("reports", 1, 0, 0),
            ("mss", 1, 1, 0), ("workplace", 1, 1, 0),
            ("timesheets", 1, 1, 0), ("digital_files", 1, 0, 0),
            ("compensation", 1, 0, 0), ("communications", 1, 0, 0),
            ("pf", 1, 0, 0), ("users", 0, 0, 0),
            ("products", 1, 1, 0), ("suppliers", 1, 1, 0),
            ("purchase_invoice", 1, 1, 0), ("purchase_return", 1, 1, 0),
            ("sales", 1, 1, 0), ("inventory", 1, 0, 0),
        ]), (emp_role, [
            ("attendance", 1, 1, 0), ("leaves", 1, 1, 0),
            ("ess", 1, 1, 0), ("reports", 0, 0, 0),
            ("mss", 0, 0, 0), ("workplace", 1, 0, 0),
            ("timesheets", 1, 1, 0), ("digital_files", 1, 0, 0),
            ("compensation", 0, 0, 0), ("communications", 1, 0, 0),
            ("pf", 1, 0, 0), ("users", 0, 0, 0),
            ("products", 0, 0, 0), ("suppliers", 0, 0, 0),
            ("purchase_invoice", 0, 0, 0), ("purchase_return", 0, 0, 0),
            ("sales", 0, 0, 0), ("inventory", 0, 0, 0),
        ])]:
            for resource, cr, cw, cd in data:
                from shared.models.base import Permission
                if not Permission.query.filter_by(role_id=role.id, resource=resource).first():
                    db.session.add(Permission(role_id=role.id, resource=resource,
                                              can_read=bool(cr), can_write=bool(cw), can_delete=bool(cd)))

        for prefix in ["PI", "PR", "CONS", "SCRAP", "ADJ", "ST", "CPV", "CRV", "BPV", "BRV", "JV", "PRL"]:
            if not VoucherNumber.query.filter_by(prefix=prefix).first():
                db.session.add(VoucherNumber(prefix=prefix, next_number=1))

        def _add_acct(code, name, type_, parent_id=None, level=4, fixed=False):
            if not ChartOfAccount.query.filter_by(code=str(code)).first():
                db.session.add(ChartOfAccount(
                    code=str(code), name=name, type=type_,
                    parent_id=parent_id, level=level, is_fixed=fixed))
            return ChartOfAccount.query.filter_by(code=str(code)).first()

        def _seed_4level_coa():
            if ChartOfAccount.query.count() > 0:
                return
            # Level 1
            l1 = {}
            for code, name, type_ in [("1", "Assets", "asset"), ("2", "Liabilities", "liability"),
                                       ("3", "Equity", "equity"), ("4", "Revenue", "revenue"),
                                       ("5", "Expense", "expense")]:
                l1[name] = _add_acct(code, name, type_, level=1, fixed=True)
            # Level 2
            l2 = {}
            l2["Current Assets"] = _add_acct("11", "Current Assets", "asset", l1["Assets"].id, 2, True)
            l2["Non-Current Assets"] = _add_acct("12", "Non-Current Assets", "asset", l1["Assets"].id, 2, True)
            l2["Current Liabilities"] = _add_acct("21", "Current Liabilities", "liability", l1["Liabilities"].id, 2, True)
            l2["Non-Current Liabilities"] = _add_acct("22", "Non-Current Liabilities", "liability", l1["Liabilities"].id, 2, True)
            l2["Equity Reserves"] = _add_acct("31", "Equity Reserves", "equity", l1["Equity"].id, 2)
            l2["Operating Revenue"] = _add_acct("41", "Operating Revenue", "revenue", l1["Revenue"].id, 2)
            l2["Operating Expenses"] = _add_acct("51", "Operating Expenses", "expense", l1["Expense"].id, 2)
            # Level 3
            l3 = {}
            l3["Cash & Bank"] = _add_acct("111", "Cash & Bank", "asset", l2["Current Assets"].id, 3, True)
            l3["Trade Debtors"] = _add_acct("112", "Trade Debtors", "asset", l2["Current Assets"].id, 3, True)
            l3["Trading Goods Stock"] = _add_acct("113", "Trading Goods Stock", "asset", l2["Current Assets"].id, 3, True)
            l3["Fixed Assets"] = _add_acct("121", "Fixed Assets", "asset", l2["Non-Current Assets"].id, 3, True)
            l3["Trade Creditors"] = _add_acct("211", "Trade Creditors", "liability", l2["Current Liabilities"].id, 3, True)
            l3["Accrued Expenses"] = _add_acct("212", "Accrued Expenses", "liability", l2["Current Liabilities"].id, 3)
            l3["Long-term Loans"] = _add_acct("221", "Long-term Loans", "liability", l2["Non-Current Liabilities"].id, 3, True)
            l3["Sales Revenue"] = _add_acct("411", "Sales Revenue", "revenue", l2["Operating Revenue"].id, 3)
            l3["Service Income"] = _add_acct("412", "Service Income", "revenue", l2["Operating Revenue"].id, 3)
            l3["Cost of Goods Sold"] = _add_acct("511", "Cost of Goods Sold", "expense", l2["Operating Expenses"].id, 3)
            l3["Salaries & Wages"] = _add_acct("512", "Salaries & Wages", "expense", l2["Operating Expenses"].id, 3)
            l3["Rent & Utilities"] = _add_acct("513", "Rent & Utilities", "expense", l2["Operating Expenses"].id, 3)
            l3["Office Supplies"] = _add_acct("514", "Office Supplies", "expense", l2["Operating Expenses"].id, 3)
            l3["Transportation"] = _add_acct("515", "Transportation", "expense", l2["Operating Expenses"].id, 3)
            l3["Taxes & Licenses"] = _add_acct("516", "Taxes & Licenses", "expense", l2["Operating Expenses"].id, 3)
            l3["Depreciation"] = _add_acct("517", "Depreciation", "expense", l2["Operating Expenses"].id, 3)
            l3["Other Expenses"] = _add_acct("519", "Other Expenses", "expense", l2["Operating Expenses"].id, 3)
            # Level 4 fixed
            _add_acct("3111", "Capital Account", "equity", l2["Equity Reserves"].id, 4, True)
            _add_acct("3112", "Retained Earnings", "equity", l2["Equity Reserves"].id, 4, True)
            _add_acct("1111", "Suspense Account", "asset", l3["Cash & Bank"].id, 4, True)
            # Payroll accounts (created by get_or_create_account at runtime, seeded here for visibility)
            _add_acct("5121", "Salary Expense", "expense", l3["Salaries & Wages"].id, 4)
            _add_acct("5122", "PF Employer Expense", "expense", l3["Salaries & Wages"].id, 4)
            _add_acct("2121", "Salary Payable", "liability", l3["Accrued Expenses"].id, 4)
            _add_acct("2122", "Income Tax Payable", "liability", l3["Accrued Expenses"].id, 4)
            _add_acct("2123", "PF Payable", "liability", l3["Accrued Expenses"].id, 4)
            _add_acct("2124", "Loan Deductions Clearing", "liability", l3["Accrued Expenses"].id, 4)

        _seed_4level_coa()

        db.session.commit()

        for u in User.query.all():
            if not u.has_hr_access and not u.has_inventory_access:
                u.has_hr_access = True
                u.has_inventory_access = (u.role_id == admin_role.id or u.role_id == mgr_role.id)

        # One-time backfill: invoicing was split out of inventory, so users who
        # had inventory access keep working in the new Invoicing module.
        if not User.query.filter_by(has_invoicing_access=True).first():
            for u in User.query.all():
                u.has_invoicing_access = bool(u.has_inventory_access)

        seed_users = [
            # Built-in system administrator — always present, hidden from the HR
            # module, manageable only via ERP hub Settings. Created once; a
            # changed password is never reset by seeding.
            ("SYSADMIN", "admin@gmail.com", "Administrator", admin_role.id, "admin123", True, True, "System Administrator"),
            ("ADM001", "admin@solarkon.com", "System Admin", admin_role.id, "admin123", True, True, "Administrator"),
            ("MGR002", "manager@solarkon.com", "Manager User", mgr_role.id, "mgr123", True, True, "Manager"),
            ("EMP001", "emp@solarkon.com", "Employee User", emp_role.id, "emp123", True, False, "Employee"),
            ("EMP002", "john.doe@solarkon.com", "John Doe", emp_role.id, "emp123", True, False, "Employee"),
        ]
        for code, email, name, rid, pw, hr, inv, desig in seed_users:
            u = User.query.filter_by(email=email).first()
            if not u:
                u = User(employee_code=code, email=email, full_name=name, role_id=rid,
                         has_hr_access=hr, has_inventory_access=inv, is_active=True, designation=desig)
                u.set_password(pw)
                db.session.add(u)

        from inventory_app.models.product import InvProduct
        from inventory_app.models.category import InvCategory
        from inventory_app.models.supplier import InvSupplier
        from inventory_app.models.customer import InvCustomer

        cat_names = ["Solar Panels", "Inverters", "Batteries", "Cables & Wiring", "Mounting Structures",
                     "Electrical Components", "Tools & Equipment", "Safety Gear"]
        cat_map = {}
        for cn in cat_names:
            c = InvCategory.query.filter_by(name=cn).first()
            if not c:
                c = InvCategory(name=cn, description=f"{cn} category")
                db.session.add(c)
                db.session.flush()
            cat_map[cn] = c.id

        for sku, name, cat, price, cost, stock, reorder in [
            ("SOL-MONO-450", "Monocrystalline Solar Panel 450W", cat_names[0], 32000, 28000, 50, 10),
            ("SOL-MONO-550", "Monocrystalline Solar Panel 550W", cat_names[0], 42000, 37000, 30, 5),
            ("SOL-POLY-330", "Polycrystalline Solar Panel 330W", cat_names[0], 22000, 18500, 40, 8),
            ("INV-5KW", "5kW Hybrid Inverter", cat_names[1], 85000, 72000, 15, 3),
            ("INV-10KW", "10kW Hybrid Inverter", cat_names[1], 145000, 125000, 10, 2),
            ("INV-3KW", "3kW String Inverter", cat_names[1], 55000, 46000, 20, 4),
            ("BAT-LFP-5KWH", "5kWh LiFePO4 Battery", cat_names[2], 180000, 155000, 25, 5),
            ("BAT-LFP-10KWH", "10kWh LiFePO4 Battery", cat_names[2], 320000, 280000, 15, 3),
            ("BAT-TUB-200", "200Ah Tubular Battery", cat_names[2], 45000, 38000, 30, 5),
            ("CBL-SOL-4MM", "Solar DC Cable 4mm (per meter)", cat_names[3], 180, 120, 500, 100),
            ("CBL-AC-2.5MM", "AC Cable 2.5mm (per meter)", cat_names[3], 120, 80, 1000, 200),
            ("CBL-MC4", "MC4 Connector Pair", cat_names[3], 350, 250, 200, 50),
            ("MNT-ALU-RACK", "Aluminum Mounting Rack (set)", cat_names[4], 8500, 6500, 20, 5),
            ("MNT-RAIL-2M", "Mounting Rail 2m", cat_names[4], 2200, 1600, 50, 10),
            ("ELEC-DB", "Distribution Board 16-way", cat_names[5], 4500, 3200, 30, 5),
            ("ELEC-SPD", "Surge Protection Device", cat_names[5], 2800, 2000, 40, 8),
            ("ELEC-MCB-16A", "MCB 16A Single Pole", cat_names[5], 350, 220, 100, 20),
            ("TOOL-CRIMP", "Solar Crimping Tool", cat_names[6], 5500, 4200, 10, 2),
            ("TOOL-MULTI", "Digital Multimeter", cat_names[6], 3500, 2500, 15, 3),
            ("SAFE-HLMT", "Safety Helmet", cat_names[7], 800, 500, 50, 10),
            ("SAFE-GLOVES", "Insulated Gloves (pair)", cat_names[7], 1200, 800, 40, 10),
            ("SAFE-HARNESS", "Safety Harness", cat_names[7], 4500, 3200, 15, 3),
        ]:
            if not InvProduct.query.filter_by(sku=sku).first():
                p = InvProduct(sku=sku, name=name, category_id=cat_map.get(cat),
                              unit_price=float(price), cost_price=float(cost),
                              current_stock=stock, reorder_level=reorder,
                              unit="pcs", is_active=True)
                db.session.add(p)

        for name, contact, email, phone, addr, city in [
            ("Longi Solar Pakistan", "Mr. Ahmed", "ahmed@longi.pk", "021-34567890", "PLOT 12, SITE AREA", "Karachi"),
            ("JA Solar Technologies", "Mr. Usman", "usman@jasolar.com", "042-35678901", "23-G, Gulberg III", "Lahore"),
            ("BYD Energy Solutions", "Mr. Kamran", "kamran@byd.com", "021-36789012", "Business Bay, Clifton", "Karachi"),
            ("Growatt Inverters", "Mr. Hassan", "hassan@growatt.com", "042-37890123", "55 Main Boulevard", "Lahore"),
            ("Al-Rashid Traders", "Mr. Rashid", "rashid@alrashid.com", "0315-1234567", "Steel Market, Bolton Market", "Karachi"),
            ("Pakistan Cable Co.", "Mr. Faisal", "faisal@pakcable.com", "021-38901234", "Industrial Area, Kot Lakhpat", "Lahore"),
        ]:
            if not InvSupplier.query.filter_by(name=name).first():
                s = InvSupplier(name=name, contact_person=contact, email=email, phone=phone,
                               address=addr, city=city, is_active=True)
                db.session.add(s)

        for name, email, phone, addr, city, cl in [
            ("SolarTech Solutions", "imran@solartech.com", "0300-1111111", "7-A, Johar Town", "Lahore", 1000000),
            ("Green Energy Pakistan", "fatima@greenenergy.com", "0300-2222222", "15-B, Phase 2, DHA", "Karachi", 2000000),
            ("BuildRight Construction", "ali@buildright.com", "0300-3333333", "3rd Floor, Al-Falah Plaza", "Islamabad", 1500000),
            ("Home Solutions Ltd.", "zafar@homesol.com", "0300-4444444", "88, Garden Town", "Lahore", 500000),
        ]:
            if not InvCustomer.query.filter_by(name=name).first():
                c = InvCustomer(name=name, email=email, phone=phone, address=addr,
                               city=city, credit_limit=cl, is_active=True)
                db.session.add(c)

        InventorySettings.get()

        from shared.models.company_settings import CompanyInfo, AccountingPeriod
        CompanyInfo.get()
        AccountingPeriod.seed_current_year()

        # Backfill level-4 subledger accounts for entities created before the
        # auto-ledger feature (idempotent — keyed on deterministic codes).
        from shared.ledger_utils import create_entity_account
        from hr_app.models.loan import LoanAdvanceRequest
        for s in InvSupplier.query.all():
            create_entity_account("supplier", s.id, s.name)
        for c in InvCustomer.query.all():
            create_entity_account("customer", c.id, c.name)
        for p in InvProduct.query.all():
            create_entity_account("product", p.id, f"{p.name} ({p.sku})")
        for u in User.query.all():
            create_entity_account("employee", u.id, f"{u.full_name} ({u.employee_code})")
            # Login id defaults to the email until the user/admin changes it.
            if not u.login_id:
                u.login_id = u.email
        for ln in LoanAdvanceRequest.query.filter(
                LoanAdvanceRequest.status.in_(["pending", "approved"])).all():
            create_entity_account("loan", ln.id,
                                  f"{ln.request_type.title()} #{ln.id} - {ln.user.full_name if ln.user else ''}")

        # Costing engine: products holding stock from before the engine get an
        # opening cost layer so every future issue has a historic cost basis.
        from shared.costing import ensure_opening_balances
        ensure_opening_balances(created_by=1)

        db.session.commit()
        print("Seed data OK")


# Export at module level for Vercel.
# _create_app() is lazy — it runs fast at import time.
# DB init happens on first request via before_request hook.
app = _create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
