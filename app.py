import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, redirect, url_for
from flask_login import current_user
from shared.config import Config
from shared.extensions import db, login_manager
from shared.models.base import User, Role, Permission, load_user
from shared.models.ledger import ChartOfAccount
from shared.models.stock_ledger import VoucherNumber, StockLedger
from shared.models.inventory_settings import InventorySettings


def register_all_blueprints(app):
    from shared.routes.dashboard import dashboard_bp
    app.register_blueprint(dashboard_bp)

    from hr_app.app import register_hr_blueprints
    register_hr_blueprints(app)

    from inventory_app.app import register_inventory_blueprints
    register_inventory_blueprints(app)


def seed_all_data(app):
    with app.app_context():
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
                if not Permission.query.filter_by(role_id=role.id, resource=resource).first():
                    db.session.add(Permission(role_id=role.id, resource=resource,
                                              can_read=bool(cr), can_write=bool(cw), can_delete=bool(cd)))

        for prefix in ["PI", "PR", "CONS", "SCRAP", "ADJ", "ST"]:
            if not VoucherNumber.query.filter_by(prefix=prefix).first():
                db.session.add(VoucherNumber(prefix=prefix, next_number=1))

        if ChartOfAccount.query.count() == 0:
            accounts = [
                ("1000", "Cash & Bank", "asset"), ("1100", "Accounts Receivable", "asset"),
                ("1200", "Inventory", "asset"), ("1300", "Fixed Assets", "asset"),
                ("2000", "Accounts Payable", "liability"), ("2100", "Accrued Expenses", "liability"),
                ("2200", "Loans Payable", "liability"), ("3000", "Owner's Equity", "equity"),
                ("3100", "Retained Earnings", "equity"), ("4000", "Sales Revenue", "revenue"),
                ("4100", "Service Income", "revenue"), ("5000", "Cost of Goods Sold", "expense"),
                ("5100", "Salaries & Wages", "expense"), ("5200", "Rent & Utilities", "expense"),
                ("5300", "Office Supplies", "expense"), ("5400", "Transportation", "expense"),
                ("5500", "Taxes & Licenses", "expense"), ("5600", "Depreciation", "expense"),
                ("5700", "Consumption Expense", "expense"),
                ("5800", "Scrap/Write-off", "expense"),
                ("5900", "Inventory Adjustment", "expense"),
            ]
            for code, name, type_ in accounts:
                db.session.add(ChartOfAccount(code=code, name=name, type=type_))
        else:
            for code, name, type_ in [
                ("5700", "Consumption Expense", "expense"),
                ("5800", "Scrap/Write-off", "expense"),
                ("5900", "Inventory Adjustment", "expense"),
            ]:
                if not ChartOfAccount.query.filter_by(code=code).first():
                    db.session.add(ChartOfAccount(code=code, name=name, type=type_))

        # Migration: add missing columns to existing tables (SQLite compat)
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        user_cols = {c["name"] for c in inspector.get_columns("users")}
        if "has_hr_access" not in user_cols:
            db.session.execute(db.text("ALTER TABLE users ADD COLUMN has_hr_access BOOLEAN DEFAULT 0"))
        if "has_inventory_access" not in user_cols:
            db.session.execute(db.text("ALTER TABLE users ADD COLUMN has_inventory_access BOOLEAN DEFAULT 0"))
        # Migration: add new columns to supplier, customer, invoice tables
        for tbl, cols in {
            "inv_suppliers": ["mobile", "tax_id", "payment_terms", "website", "notes"],
            "inv_customers": ["contact_person", "mobile", "tax_id", "payment_terms", "website", "notes"],
            "inv_invoices": ["discount_mode", "tax_mode", "global_discount_pct", "global_discount_value", "global_sales_tax_pct", "subtotal", "total_discount", "total_tax", "notes", "created_by"],
            "inventory_settings": ["purchase_flow", "sales_flow"],
        }.items():
            existing = {c["name"] for c in inspector.get_columns(tbl)}
            for col in cols:
                if col not in existing:
                    try:
                        db.session.execute(db.text(f"ALTER TABLE {tbl} ADD COLUMN {col} VARCHAR(200) DEFAULT ''"))
                    except:
                        db.session.rollback()
        db.session.commit()

        for u in User.query.all():
            if not u.has_hr_access and not u.has_inventory_access:
                u.has_hr_access = True
                u.has_inventory_access = (u.role_id == admin_role.id or u.role_id == mgr_role.id)

        if not User.query.filter_by(email="admin@solarkon.com").first():
            u = User(
                employee_code="ADM001", email="admin@solarkon.com",
                full_name="System Admin", role_id=admin_role.id,
                has_hr_access=True, has_inventory_access=True,
                is_active=True, designation="Administrator"
            )
            u.set_password("admin123")
            db.session.add(u)

        if not User.query.filter_by(email="manager@solarkon.com").first():
            u = User(
                employee_code="MGR002", email="manager@solarkon.com",
                full_name="Manager User", role_id=mgr_role.id,
                has_hr_access=True, has_inventory_access=True,
                is_active=True, designation="Manager"
            )
            u.set_password("mgr123")
            db.session.add(u)
        else:
            u = User.query.filter_by(email="manager@solarkon.com").first()
            u.has_hr_access = True
            u.has_inventory_access = True

        if not User.query.filter_by(email="emp@solarkon.com").first():
            u = User(
                employee_code="EMP001", email="emp@solarkon.com",
                full_name="Employee User", role_id=emp_role.id,
                has_hr_access=True, has_inventory_access=False,
                is_active=True, designation="Employee"
            )
            u.set_password("emp123")
            db.session.add(u)

        # john.doe@solarkon.com - existing user from old HR seed
        existing = User.query.filter_by(email="john.doe@solarkon.com").first()
        if existing:
            existing.has_hr_access = True
            existing.has_inventory_access = False
        else:
            u = User(
                employee_code="EMP002", email="john.doe@solarkon.com",
                full_name="John Doe", role_id=emp_role.id,
                has_hr_access=True, has_inventory_access=False,
                is_active=True, designation="Employee"
            )
            u.set_password("emp123")
            db.session.add(u)

        # Inventory seed data
        from inventory_app.models.product import InvProduct
        from inventory_app.models.category import InvCategory
        from inventory_app.models.supplier import InvSupplier
        from inventory_app.models.customer import InvCustomer
        inv_admin_id = User.query.filter_by(email="admin@solarkon.com").first().id

        # Categories
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

        # Products
        seed_products = [
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
        ]
        for sku, name, cat, price, cost, stock, reorder in seed_products:
            if not InvProduct.query.filter_by(sku=sku).first():
                p = InvProduct(sku=sku, name=name, category_id=cat_map.get(cat),
                              unit_price=float(price), cost_price=float(cost),
                              current_stock=stock, reorder_level=reorder,
                              unit="pcs", is_active=True)
                db.session.add(p)

        # Suppliers (InvSupplier: name, contact_person, email, phone, address, city, is_active)
        seed_suppliers = [
            ("Longi Solar Pakistan", "Mr. Ahmed", "ahmed@longi.pk", "021-34567890",
             "PLOT 12, SITE AREA", "Karachi"),
            ("JA Solar Technologies", "Mr. Usman", "usman@jasolar.com", "042-35678901",
             "23-G, Gulberg III", "Lahore"),
            ("BYD Energy Solutions", "Mr. Kamran", "kamran@byd.com", "021-36789012",
             "Business Bay, Clifton", "Karachi"),
            ("Growatt Inverters", "Mr. Hassan", "hassan@growatt.com", "042-37890123",
             "55 Main Boulevard", "Lahore"),
            ("Al-Rashid Traders", "Mr. Rashid", "rashid@alrashid.com", "0315-1234567",
             "Steel Market, Bolton Market", "Karachi"),
            ("Pakistan Cable Co.", "Mr. Faisal", "faisal@pakcable.com", "021-38901234",
             "Industrial Area, Kot Lakhpat", "Lahore"),
        ]
        for name, contact, email, phone, addr, city in seed_suppliers:
            if not InvSupplier.query.filter_by(name=name).first():
                s = InvSupplier(name=name, contact_person=contact, email=email, phone=phone,
                               address=addr, city=city, is_active=True)
                db.session.add(s)

        # Customers (InvCustomer: name, email, phone, address, city, credit_limit, is_active)
        seed_customers = [
            ("SolarTech Solutions", "imran@solartech.com", "0300-1111111",
             "7-A, Johar Town", "Lahore", 1000000),
            ("Green Energy Pakistan", "fatima@greenenergy.com", "0300-2222222",
             "15-B, Phase 2, DHA", "Karachi", 2000000),
            ("BuildRight Construction", "ali@buildright.com", "0300-3333333",
             "3rd Floor, Al-Falah Plaza", "Islamabad", 1500000),
            ("Home Solutions Ltd.", "zafar@homesol.com", "0300-4444444",
             "88, Garden Town", "Lahore", 500000),
        ]
        for name, email, phone, addr, city, cl in seed_customers:
            if not InvCustomer.query.filter_by(name=name).first():
                c = InvCustomer(name=name, email=email, phone=phone, address=addr,
                               city=city, credit_limit=cl, is_active=True)
                db.session.add(c)

        InventorySettings.get()
        db.session.commit()
        print("Seed data OK")


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
        static_url_path="/static",
    )

    app.config.from_object(Config)

    import jinja2

    my_loader = jinja2.ChoiceLoader(
        [
            app.jinja_loader,
            jinja2.FileSystemLoader(
                [
                    os.path.join(os.path.dirname(__file__), "hr_app", "templates"),
                    os.path.join(os.path.dirname(__file__), "inventory_app", "templates"),
                ]
            ),
        ]
    )
    app.jinja_loader = my_loader

    db.init_app(app)
    login_manager.init_app(app)

    register_all_blueprints(app)

    @app.context_processor
    def inject_now():
        return {"now": __import__("datetime").datetime.utcnow()}

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.hub"))
        return redirect(url_for("auth.login"))

    import traceback

    @app.errorhandler(500)
    def handle_500(e):
        tb = traceback.format_exc()
        return f"<pre style='background:#fef2f2;padding:20px;border:2px solid #ef4444;border-radius:8px;font-size:13px;overflow:auto;max-height:90vh;'>{tb}</pre>", 500

    @app.errorhandler(Exception)
    def handle_all(e):
        tb = traceback.format_exc()
        return f"<pre style='background:#fef2f2;padding:20px;border:2px solid #ef4444;border-radius:8px;font-size:13px;overflow:auto;max-height:90vh;'>{tb}</pre>", 500

    with app.app_context():
        try:
            db.create_all()
            seed_all_data(app)
        except Exception as e:
            import traceback
            print("DB INIT ERROR:", e)
            traceback.print_exc()

    return app


try:
    app = create_app()
except Exception as e:
    import traceback
    print("FATAL: App creation failed:", e)
    traceback.print_exc()
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"

    @app.route("/")
    @app.route("/<path:path>")
    def error_route(path=""):
        return f"<pre style='background:#fef2f2;padding:20px;border:2px solid #ef4444;border-radius:8px;font-size:13px;overflow:auto;max-height:90vh;'>App failed to start:\n{traceback.format_exc()}</pre>", 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
