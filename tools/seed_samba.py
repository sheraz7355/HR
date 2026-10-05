"""Seed a full financial year of trading for Samba Private Limited.

Samba Private Limited is a solar-equipment trader in Lahore: panels,
inverters, lithium batteries, mounting structures and balance-of-system
items, sold to dealers, installers, project clients and walk-in customers.
This script creates the company and drives one year of business, 1 July 2025
to 30 June 2026, through the app's REAL routes (the same JSON and form posts
the screens send), in date order. Costing, stock, journals, sub-ledgers and
the reporting table all come out exactly as if a person had keyed every
document.

Roughly 7,500 documents:

    sales orders / purchase orders            ~300 / ~280   (billed later, some in parts)
    purchase invoices                         ~650
    sales invoices                            ~2,700
    sales / purchase returns                  ~110
    customer receipts (CRV / BRV)             ~1,500
    supplier payments (BPV)                   ~700
    expense payments (CPV / BPV)              ~1,100
    journal vouchers                          ~150
    consumption / scrap vouchers              ~40

The invoices use the invoice settings the way a real business would:

    combined and per-line discount; combined and per-line sales tax
    further tax on unregistered buyers; income-tax withholding by corporate
    project clients and on some suppliers
    additional charges in all three treatments: billed to the other party
    (delivery, installation, supplier's loading), absorbed into the goods
    (free delivery, carriage inward capitalised into stock) and borne by us
    (site transport, clearing agent) — plus per-line freight on purchases

Usage (from the repo root):

    venv/Scripts/python tools/seed_samba.py                    # DATABASE_URL or the dev DB
    venv/Scripts/python tools/seed_samba.py --database-url postgresql://...
    venv/Scripts/python tools/seed_samba.py --scale 0.1        # a quick ~750-document run

The company is owned by the first super admin. The script stops if a company
with the same slug already exists; pass --slug to seed another copy, or
--company-id to fill a company already created in the app (posting as its
admin; refused if it already has journal entries).
"""
import argparse
import os
import random
import sys
import time
from collections import defaultdict, deque
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FY_START = date(2025, 7, 1)
FY_END = date(2026, 6, 30)
TAX = 18.0
FURTHER = 4.0
# Per-line sales tax by category, for invoices that tax line by line.
LINE_TAX = {"panel": 10.0, "inverter": 18.0, "battery": 18.0, "structure": 18.0, "bos": 18.0}

# Monthly weight of trade: solar sells hardest in spring and early summer.
SEASON = {7: 1.10, 8: 1.00, 9: 0.95, 10: 0.85, 11: 0.75, 12: 0.70,
          1: 0.75, 2: 0.90, 3: 1.10, 4: 1.25, 5: 1.35, 6: 1.30}

# sku, name, unit, category, cost, sale price, purchase pack, target stock
PRODUCTS = [
    ("PNL-LG-550", "Longi Hi-MO 550W Mono PERC Panel", "pcs", "panel", 14800, 17200, 36, 900),
    ("PNL-LG-585", "Longi Hi-MO 6 585W Bifacial Panel", "pcs", "panel", 16900, 19600, 36, 700),
    ("PNL-JK-575", "Jinko Tiger Neo 575W N-Type Panel", "pcs", "panel", 16200, 18900, 36, 700),
    ("PNL-CS-545", "Canadian Solar 545W HiKu Panel", "pcs", "panel", 14300, 16700, 36, 500),
    ("PNL-TR-600", "Trina Vertex 600W Panel", "pcs", "panel", 17600, 20500, 31, 400),
    ("INV-GW-6K", "Growatt 6kW Hybrid Inverter", "pcs", "inverter", 168000, 194000, 5, 60),
    ("INV-GW-10K", "Growatt 10kW On-Grid Inverter", "pcs", "inverter", 215000, 249000, 4, 40),
    ("INV-HW-10K", "Huawei SUN2000 10kW Inverter", "pcs", "inverter", 298000, 342000, 4, 35),
    ("INV-SL-15K", "Solis 15kW Three-Phase Inverter", "pcs", "inverter", 365000, 419000, 3, 20),
    ("INV-IX-6K", "Inverex Nitrox 6kW Hybrid Inverter", "pcs", "inverter", 152000, 176000, 6, 60),
    ("INV-KN-5K", "Knox 5kW Hybrid Inverter", "pcs", "inverter", 118000, 137000, 6, 50),
    ("BAT-PY-5K", "Pylontech US5000 4.8kWh Lithium Battery", "pcs", "battery", 285000, 326000, 4, 40),
    ("BAT-DY-5K", "Dyness 5.12kWh Lithium Battery", "pcs", "battery", 248000, 286000, 4, 40),
    ("BAT-NR-200", "Narada 12V 200Ah Tubular Battery", "pcs", "battery", 52000, 61000, 10, 80),
    ("STR-GI-4", "GI Mounting Structure (4 panels)", "set", "structure", 18500, 23500, 10, 150),
    ("STR-L2-6", "L2 Elevated Structure (6 panels)", "set", "structure", 34000, 42500, 6, 80),
    ("CBL-DC-6", "DC Solar Cable 6mm (100 m)", "roll", "bos", 21500, 25500, 10, 120),
    ("CBL-AC-10", "AC Cable 10mm 4-Core (100 m)", "roll", "bos", 64000, 74500, 4, 40),
    ("BOS-MC4", "MC4 Connector Pair", "pair", "bos", 280, 450, 200, 2500),
    ("BOS-DCB-32", "DC Breaker 32A 1000V", "pcs", "bos", 2900, 3900, 50, 400),
    ("BOS-SPD", "DC Surge Protection Device", "pcs", "bos", 3600, 4800, 40, 300),
    ("BOS-ERTH", "Earthing Kit (rod + chemical)", "set", "bos", 7800, 10500, 20, 120),
    ("BOS-DB-PV", "PV Combiner / Distribution Box", "pcs", "bos", 9600, 12800, 20, 120),
    ("MTR-NET-3P", "Net-Metering Bi-Directional Meter 3-Phase", "pcs", "bos", 38000, 46000, 6, 40),
]

# name, category, city, withholds income tax on our payments (filer company)
SUPPLIERS = [
    ("Crescent Solar Imports", "panel", "Karachi", True),
    ("Indus PV Distribution", "panel", "Lahore", False),
    ("Sunrise Energy Traders", "panel", "Lahore", False),
    ("Ravi Power Systems", "inverter", "Lahore", True),
    ("Margalla Inverter House", "inverter", "Islamabad", False),
    ("Arabian Sea Electronics", "inverter", "Karachi", True),
    ("Volt Storage (Pvt) Ltd", "battery", "Karachi", True),
    ("Kohinoor Battery Co.", "battery", "Lahore", False),
    ("Punjab Steel Structures", "structure", "Gujranwala", False),
    ("Shalimar Fabricators", "structure", "Lahore", False),
    ("Pak Cables & Accessories", "bos", "Lahore", True),
    ("Metro Electric Supplies", "bos", "Faisalabad", False),
]

CITIES = ["Lahore", "Lahore", "Lahore", "Gujranwala", "Faisalabad", "Sialkot",
          "Sheikhupura", "Kasur", "Okara", "Sahiwal", "Multan", "Gujrat"]
DEALER_WORDS = ["Solar", "Energy", "Power", "Electric", "Solar Hub", "Green Energy",
                "Sun Tech", "Electronics", "Traders", "Renewables"]
NAMES = ["Al-Noor", "Madina", "Haider", "Bismillah", "Ittefaq", "Khan", "Rehman",
         "Faisal", "Qadri", "Usman", "Zam Zam", "Al-Hamd", "Shaheen", "Kashmir",
         "Hamza", "Ali", "Pak", "Rizwan", "Bilal", "Saad", "Fateh", "Iqra", "Noor",
         "Chaudhry", "Abbasi", "Sheikh", "Mughal", "Butt", "Malik", "Gondal"]
PROJECT_CLIENTS = ["Riverside Textile Mills", "Green Valley School System",
                   "Shadman Medical Centre", "DHA Phase 6 Residence Block",
                   "Gulberg Office Tower", "Pak Arab Housing Society", "Ferozepur Road Cold Storage",
                   "Model Town Marriage Hall", "Sundar Industrial Estate Unit 12",
                   "Johar Town Hostel", "Bahria Orchard Mosque Trust", "Wapda Town Clinic",
                   "Raiwind Poultry Farm", "Sheikhupura Rice Mill", "Kasur Leather Works",
                   "Lake City Villas", "Valencia Commercial Plaza", "Askari 11 Residence",
                   "Thokar Niaz Baig Flour Mill", "Allama Iqbal Town Hospital"]


def r2(x):
    return round(x + 0.0, 2)


def rprice(x):
    return round(x, -1 if x < 5000 else -2)


class Seeder:
    def __init__(self, app, scale, slug, rng, company_id=None):
        self.company_id = company_id
        self.app = app
        self.c = app.test_client()
        self.scale = scale
        self.slug = slug
        self.rng = rng
        self.count = defaultdict(int)
        self.t0 = time.time()
        self.today = FY_START

    # ── plumbing ──────────────────────────────────────────────────

    def ctx(self):
        from shared.tenancy import set_current_company
        cm = self.app.app_context()
        cm.push()
        set_current_company(self.cid)
        return cm

    def query(self, fn):
        """Run a read inside the company's context."""
        from shared.extensions import db
        cm = self.ctx()
        try:
            return fn()
        finally:
            db.session.remove()
            cm.pop()

    def _done(self, kind):
        self.count[kind] += 1
        n = sum(self.count.values())
        if n % 20 == 0:
            # Form posts flash a message for a page the script never opens;
            # left alone they pile up in the session cookie.
            with self.c.session_transaction() as s:
                s.pop("_flashes", None)
        if n % 250 == 0:
            el = time.time() - self.t0
            print(f"  {n:>5} documents  {self.today}  ({el / 60:.1f} min)", flush=True)

    def post_json(self, url, payload, kind):
        r = self.c.post(url, json=payload)
        body = r.get_json(silent=True) or {}
        if r.status_code != 200 or not body.get("ok"):
            raise RuntimeError(f"{kind} on {self.today} refused: "
                               f"{r.status_code} {r.get_data(as_text=True)[:400]}")
        self._done(kind)
        return body

    def post_form(self, url, data, kind):
        r = self.c.post(url, data=data)
        if r.status_code != 302:
            # A 200 from a form post is the form re-rendered with an error.
            raise RuntimeError(f"{kind} on {self.today} refused: {r.status_code} "
                               f"{r.get_data(as_text=True)[:600]}")
        self._done(kind)

    # ── company and master data ───────────────────────────────────

    def setup(self):
        from shared.extensions import db
        from hr_app.models.user import User
        from shared.models.company import Company, CompanyMembership
        from shared.models.base import Role
        from shared.tenancy import set_current_company, unscoped
        from shared.company_setup import provision_company

        self.c.get("/")  # boot: create_all, migrations, seed
        with self.app.app_context():
            if self.company_id:
                self._existing_company()
                return self._finish_setup()
            user = (User.query.filter_by(is_super_admin=True).order_by(User.id).first()
                    or User.query.order_by(User.id).first())
            self.uid = user.id
            with unscoped():
                if Company.query.filter_by(slug=self.slug).first():
                    sys.exit(f"A company with slug '{self.slug}' already exists. "
                             f"Pass --slug to seed another copy.")
                comp = Company(name="Samba Private Limited", slug=self.slug,
                               is_active=True, created_by=self.uid)
                db.session.add(comp)
                db.session.flush()
                admin = Role.query.filter_by(name=Role.ADMIN).first()
                db.session.add(CompanyMembership(company_id=comp.id, user_id=self.uid,
                                                 role_id=admin.id,
                                                 status=CompanyMembership.ACTIVE))
                db.session.commit()
                self.cid = comp.id
            set_current_company(self.cid)
            provision_company(self.cid)
            set_current_company(self.cid)
            self._finish_setup()

    def _existing_company(self):
        """Fill a company that was already created (and provisioned) in the
        app: post as its admin member. Refuses a company with trade in it."""
        from shared.models.company import Company, CompanyMembership
        from shared.models.base import Role
        from shared.models.ledger import JournalEntry
        from shared.tenancy import set_current_company, unscoped
        from shared.company_setup import provision_company
        with unscoped():
            comp = Company.query.get(self.company_id)
            if comp is None:
                sys.exit(f"No company with id {self.company_id}.")
            admin = Role.query.filter_by(name=Role.ADMIN).first()
            m = (CompanyMembership.query.filter_by(company_id=comp.id, role_id=admin.id,
                                                   status=CompanyMembership.ACTIVE)
                 .order_by(CompanyMembership.id).first())
            if m is None:
                sys.exit(f"Company {comp.id} has no active admin member to post as.")
            self.uid = m.user_id
            self.cid = comp.id
            if JournalEntry.query.filter_by(company_id=comp.id).count():
                sys.exit(f"Company {comp.id} ({comp.name}) already has journal entries; "
                         f"the seed only fills an empty company.")
        set_current_company(self.cid)
        provision_company(self.cid)   # idempotent: fills anything missing
        set_current_company(self.cid)

    def _finish_setup(self):
        from shared.extensions import db
        self._company_details()
        self._accounts()
        self._masters()
        db.session.commit()

    def login(self):
        with self.c.session_transaction() as s:
            s["_user_id"] = str(self.uid)
            s["_fresh"] = True
            s["company_id"] = self.cid

    def _company_details(self):
        from shared.extensions import db
        from shared.models.company_settings import CompanyInfo, FiscalYearRule
        info = CompanyInfo.get()
        info.company_name = "Samba Private Limited"
        info.address = "Plot 41, Hall Road Commercial Area"
        info.city = "Lahore"
        info.state = "Punjab"
        info.country = "Pakistan"
        info.phone = "+92 42 3735 0441"
        info.email = "accounts@samba.pk"
        info.website = "www.samba.pk"
        info.tax_id = "NTN 7712044-6"
        info.registration_number = "STRN 3277876154812"
        info.bank_name = "Meezan Bank"
        info.bank_account_title = "Samba Private Limited"
        info.bank_account_number = "0102-0105781334"
        info.fiscal_year_start_month = 7
        rule = FiscalYearRule.get()
        rule.start_month, rule.start_day = 7, 1
        db.session.flush()
        rule.generate_periods(2025, 2026)

    def _accounts(self):
        from shared.extensions import db
        from shared.models.ledger import ChartOfAccount as A
        from shared.coa import next_child_code
        from shared.ledger_utils import posting_account
        need = {
            "cash": "1-01-01-01-0001", "capital": "3-01-01-01-0001",
            "salary": "5-02-01-01-0001", "rent": "5-02-02-01-0001",
            "utilities": "5-02-02-01-0002", "office": "5-02-03-01-0001",
            "fees": "5-02-05-01-0001", "freight": "5-03-01-01-0001",
            "commission": "5-03-02-01-0001", "marketing": "5-03-03-01-0001",
            "other": "5-04-01-01-0001", "bankchg": "5-05-01-01-0001",
            "salary_payable": "2-01-02-02-0001",
            "output_tax": "2-01-03-01-0001", "input_tax": "1-01-05-01-0001",
        }
        self.acc = {}
        for key, code in need.items():
            a = A.query.filter_by(code=code).first()
            if a is None:
                sys.exit(f"Chart of accounts has no {code} ({key}); was the company provisioned?")
            self.acc[key] = a.id
        # The exact accounts the invoice postings use for these roles.
        for key, role in (("accrued", "accrued"), ("wht_payable", "wht_payable"),
                          ("further_tax", "further_tax_payable")):
            self.acc[key] = posting_account(role).id

        def ensure(parent_code, name, type_):
            parent = A.query.filter_by(code=parent_code).first()
            a = A.query.filter_by(parent_id=parent.id, name=name).first()
            if a is None:
                a = A(code=next_child_code(parent), name=name, type=type_,
                      parent_id=parent.id, level=parent.level + 1)
                db.session.add(a)
                db.session.flush()
            return a.id

        self.acc["bank"] = ensure("1-01-01-02", "Meezan Bank — Current A/c 0105781334", "asset")
        self.acc["bank2"] = ensure("1-01-01-02", "HBL — Business A/c 1247-7901", "asset")
        self.acc["delivery_income"] = ensure("4-03-01-01", "Delivery Charges Recovered", "revenue")
        self.acc["install_income"] = ensure("4-03-01-01", "Installation & Commissioning Income", "revenue")
        self.acc["carriage_in"] = ensure("5-03-01-01", "Carriage Inward & Loading", "expense")
        self.acc["clearing"] = ensure("5-03-01-01", "Clearing & Forwarding Charges", "expense")

    def _masters(self):
        from shared.extensions import db
        from inventory_app.models.product import InvProduct
        from inventory_app.models.supplier import InvSupplier
        from inventory_app.models.customer import InvCustomer
        from shared.models.project_label import ProjectLabel
        from shared.ledger_utils import create_entity_account
        rng = self.rng

        self.labels = {}
        for key, name in [("retail", "Retail Counter"), ("dealer", "Dealer Network"),
                          ("project", "Solar Projects")]:
            lb = ProjectLabel(name=name)
            db.session.add(lb)
            db.session.flush()
            self.labels[key] = lb.id

        self.products = []
        for sku, name, unit, cat, cost, price, pack, target in PRODUCTS:
            p = InvProduct(sku=sku, name=name, unit=unit, unit_price=price,
                           cost_price=cost, current_stock=0)
            db.session.add(p)
            db.session.flush()
            self.products.append({"id": p.id, "sku": sku, "name": name, "unit": unit,
                                  "cat": cat, "cost": cost, "price": price,
                                  "pack": pack, "target": target})
        self.P = {p["sku"]: p for p in self.products}
        self.by_cat = defaultdict(list)
        for p in self.products:
            self.by_cat[p["cat"]].append(p)

        self.suppliers = []
        for name, cat, city, withholds in SUPPLIERS:
            terms = rng.choice([15, 30, 45])
            s = InvSupplier(name=name, city=city, contact_person=rng.choice(NAMES) + " Sahib",
                            phone=f"+92 3{rng.randint(0, 4)}{rng.randint(0, 9)} {rng.randint(1000000, 9999999)}",
                            payment_terms=f"{terms} days", tax_id=f"{rng.randint(1000000, 9999999)}-{rng.randint(0, 9)}",
                            address=f"{rng.randint(1, 200)} Main Market, {city}")
            db.session.add(s)
            db.session.flush()
            self.suppliers.append({"id": s.id, "name": name, "cat": cat, "terms": terms,
                                   "wht": withholds,
                                   "acct": create_entity_account("supplier", s.id, name).id})

        self.customers = []
        walk = InvCustomer(name="Cash Sales — Walk-in", city="Lahore", payment_terms="Cash")
        db.session.add(walk)
        db.session.flush()
        self.walkin = {"id": walk.id, "name": walk.name, "kind": "retail", "registered": False,
                       "acct": create_entity_account("customer", walk.id, walk.name).id}
        used = set()

        def unique(fmt):
            while True:
                name = fmt()
                if name not in used:
                    used.add(name)
                    return name
        for _ in range(70):
            self._customer(unique(lambda: f"{rng.choice(NAMES)} {rng.choice(DEALER_WORDS)}"),
                           "dealer", rng.choice([15, 30, 30, 45]), registered=rng.random() < 0.8)
        for name in PROJECT_CLIENTS:
            self._customer(name, "project", rng.choice([30, 45, 60]), registered=True)
        for _ in range(25):
            self._customer(unique(lambda: f"{rng.choice(NAMES)} Solar Installers"),
                           "installer", rng.choice([7, 15, 30]), registered=rng.random() < 0.5)
        # A few heavyweights buy far more than the rest.
        for c in self.customers:
            c["weight"] = rng.choice([1, 1, 1, 2, 2, 3, 6]) if c["kind"] != "project" else 1

    def _customer(self, name, kind, terms, registered):
        from shared.extensions import db
        from inventory_app.models.customer import InvCustomer
        from shared.ledger_utils import create_entity_account
        rng = self.rng
        city = rng.choice(CITIES)
        c = InvCustomer(name=name, city=city, payment_terms=f"{terms} days",
                        contact_person=rng.choice(NAMES),
                        mobile=f"03{rng.randint(0, 4)}{rng.randint(0, 9)}-{rng.randint(1000000, 9999999)}",
                        tax_id=f"{rng.randint(1000000, 9999999)}-{rng.randint(0, 9)}" if registered else None,
                        credit_limit=rng.choice([2_000_000, 5_000_000, 10_000_000, 25_000_000]),
                        address=f"Shop {rng.randint(1, 300)}, {city}")
        db.session.add(c)
        db.session.flush()
        self.customers.append({"id": c.id, "name": name, "kind": kind, "terms": terms,
                               "registered": registered,
                               "acct": create_entity_account("customer", c.id, name).id,
                               "cycle": rng.randint(18, 32),
                               "next_pay": FY_START + timedelta(days=rng.randint(15, 40))})

    # ── simulation state ──────────────────────────────────────────

    def init_state(self):
        rng = self.rng
        self.stock = {p["id"]: 0 for p in self.products}
        self.ar = defaultdict(deque)       # customer id -> deque[[date, amount]]
        self.ap = defaultdict(deque)       # supplier id -> deque[[date, amount]]
        self.cash = 0.0
        self.bank = 0.0
        self.cash_sales_today = 0.0
        self.m = defaultdict(float)        # this month's tax and accrual running totals
        self.pending_month = None
        self.done_tags = set()
        self.recent_sales = deque()        # (date, invoice id, customer, discount pct)
        self.recent_purchases = deque()    # (date, invoice id, supplier)
        self.pending = []                  # (due date, seq, kind, payload) order billings
        self.seq = 0
        self.on_order = {}                 # product id -> qty on open purchase orders
        for s in self.suppliers:
            s["next_pay"] = FY_START + timedelta(days=rng.randint(10, 20))
            s["cycle"] = rng.randint(5, 9)

    def schedule(self, due, kind, payload):
        self.seq += 1
        self.pending.append((due, self.seq, kind, payload))

    # ── the year ──────────────────────────────────────────────────

    def run(self):
        self.init_state()
        sc = self.scale
        work_days = [FY_START + timedelta(days=i)
                     for i in range((FY_END - FY_START).days + 1)
                     if (FY_START + timedelta(days=i)).weekday() != 6]
        wsum = sum(SEASON[d.month] for d in work_days)
        self.work_days = work_days
        carry = defaultdict(float)

        def draw(key, total, d):
            """Fractional daily rate → whole count, carrying the remainder."""
            carry[key] += total * sc * SEASON[d.month] / wsum
            n = int(carry[key])
            carry[key] -= n
            return n
        self.draw = draw

        for d in work_days:
            self.today = d
            if d == FY_START:
                self.opening()
            # Orders falling due are billed first, then the day's own trade.
            self.bill_due_orders(d)
            for _ in range(draw("pi", 640, d)):
                self.purchase(d)
            self.restock_if_short(d)
            for _ in range(draw("si", 2650, d)):
                self.sale(d)
            for _ in range(draw("sr", 70, d)):
                self.sales_return(d)
            for _ in range(draw("pr", 40, d)):
                self.purchase_return(d)
            for _ in range(draw("cv", 40, d)):
                self.stock_voucher(d)
            self.walkin_receipt(d)
            self.customer_receipts(d)
            self.supplier_payments(d)
            self.daily_expenses(d)
            self.month_events(d)
            if d.weekday() in (1, 4):
                self.deposit_cash(d)

    # ── opening ───────────────────────────────────────────────────

    def opening(self):
        d = self.today
        self.jv(d, "Share capital subscribed and paid in by the directors",
                [(self.acc["bank"], 150_000_000, 0, "Capital paid into Meezan Bank"),
                 (self.acc["capital"], 0, 150_000_000, "Share capital — 15,000,000 shares of Rs 10")])
        self.bank += 150_000_000
        self.jv(d, "Opening float for the cash counter",
                [(self.acc["cash"], 1_500_000, 0, "Counter float"),
                 (self.acc["bank"], 0, 1_500_000, "Cash withdrawn for counter float")])
        self.bank -= 1_500_000
        self.cash += 1_500_000
        # Initial stocking: one invoice per supplier for every line it carries.
        for s in self.suppliers:
            self.purchase(d, supplier=s, initial=True)

    # ── purchasing ────────────────────────────────────────────────

    def _purchase_lines(self, supplier, initial=False):
        rng = self.rng
        lines = []
        for p in self.by_cat[supplier["cat"]]:
            gap = p["target"] - self.stock[p["id"]] - self.on_order.get(p["id"], 0)
            if initial:
                qty = p["target"] * rng.uniform(0.25, 0.45)
            elif gap > 0 and rng.random() < 0.85:
                qty = gap * rng.uniform(0.25, 0.6)
            elif rng.random() < 0.15:
                qty = p["pack"]
            else:
                continue
            qty = max(1, round(qty / p["pack"])) * p["pack"]
            # Import prices drift with the rupee and the freight market.
            lines.append((p, qty, rprice(p["cost"] * rng.uniform(0.96, 1.05))))
        if not lines:
            p = rng.choice(self.by_cat[supplier["cat"]])
            lines = [(p, p["pack"], p["cost"])]
        return lines

    def purchase(self, d, supplier=None, initial=False):
        rng = self.rng
        if supplier is None:
            # A supplier whose category is emptiest relative to its targets.
            def need(s):
                return sum(max(0, p["target"] - self.stock[p["id"]] - self.on_order.get(p["id"], 0))
                           * p["cost"] for p in self.by_cat[s["cat"]])
            supplier = rng.choice(sorted(self.suppliers, key=need, reverse=True)[:5])
        lines = self._purchase_lines(supplier, initial)
        if not initial and rng.random() < 0.45:
            self.purchase_order(d, supplier, lines)
            return
        self.purchase_invoice(d, supplier, [(p, q, pr, None) for p, q, pr in lines])

    def purchase_order(self, d, supplier, lines):
        rng = self.rng
        sub = r2(sum(q * pr for _, q, pr in lines))
        tax = r2(sub * TAX / 100)
        body = self.post_json("/inventory/purchases/save", {
            "supplier_id": supplier["id"], "order_date": d.isoformat(),
            "expected_date": (d + timedelta(days=10)).isoformat(),
            "tax_mode": "general", "global_sales_tax_pct": TAX,
            "notes": rng.choice(["Confirmed on WhatsApp", "Rate locked for 15 days",
                                 "Deliver to Ferozepur Road warehouse", "Partial deliveries accepted"]),
            "subtotal": sub, "total_tax": tax, "total_amount": r2(sub + tax),
            "items": [{"product_id": p["id"], "description": p["name"], "quantity": q,
                       "unit": p["unit"], "unit_price": pr, "sales_tax_pct": 0,
                       "total_before_discount": r2(q * pr), "total_after_discount": r2(q * pr),
                       "total_price": r2(q * pr)} for p, q, pr in lines],
            "action": "approve"}, "purchase_order")
        from inventory_app.models.purchase_order import InvPurchaseOrderItem
        rows = self.query(lambda: [(i.id, i.product_id, float(i.quantity), float(i.unit_price))
                                   for i in InvPurchaseOrderItem.query.filter_by(po_id=body["id"]).all()])
        byp = {p["id"]: p for p, _, _ in lines}
        for _, pid, q, _ in rows:
            self.on_order[pid] = self.on_order.get(pid, 0) + q
        items = [{"order_item": oid, "p": byp[pid], "qty": q, "price": pr} for oid, pid, q, pr in rows]
        # Most arrive in one delivery; a fifth come in two.
        if rng.random() < 0.2 and len(items) > 1:
            first = [dict(it, qty=it["qty"] if i % 2 == 0 else 0) for i, it in enumerate(items)]
            second = [dict(it, qty=0 if i % 2 == 0 else it["qty"]) for i, it in enumerate(items)]
            self.schedule(d + timedelta(days=rng.randint(4, 10)), "po",
                          {"po": body["id"], "supplier": supplier, "items": first})
            self.schedule(d + timedelta(days=rng.randint(12, 20)), "po",
                          {"po": body["id"], "supplier": supplier, "items": second})
        else:
            self.schedule(d + timedelta(days=rng.randint(4, 14)), "po",
                          {"po": body["id"], "supplier": supplier, "items": items})

    def purchase_invoice(self, d, supplier, lines, po_id=None):
        """lines: (product, qty, price, order item id or None)."""
        rng = self.rng
        A = self.acc
        line_disc = rng.random() < 0.15
        line_tax = rng.random() < 0.15
        gdisc_pct = 0 if line_disc else rng.choice([0, 0, 0, 0, 1, 1.5, 2])
        items, total_base, tax_lines, per_item_freight = [], 0.0, 0.0, 0.0
        for p, q, pr, oid in lines:
            before = r2(q * pr)
            dpct = rng.choice([0, 1, 2, 2.5]) if line_disc else 0
            after = r2(before * (1 - dpct / 100))
            freight = rprice(before * rng.uniform(0.003, 0.01)) if rng.random() < 0.12 else 0
            rate = LINE_TAX[p["cat"]] if line_tax else 0
            total_base += after
            per_item_freight += freight
            tax_lines += r2((after + freight) * rate / 100)
            items.append({"product_id": p["id"], "quantity": q, "unit_price": pr,
                          "discount_pct": dpct, "discount_amount": r2(before - after),
                          "freight": freight, "sales_tax_pct": rate,
                          "total_before_discount": before, "total_after_discount": after,
                          "source_order_id": po_id, "source_order_item_id": oid})
        sub = r2(sum(it["total_before_discount"] for it in items))
        total_base = r2(total_base)
        gdisc = r2(total_base * gdisc_pct / 100)
        charges = []
        if rng.random() < 0.35:
            charges.append({"description": "Carriage inward", "treatment": "absorb",
                            "charge_account_id": A["carriage_in"],
                            "amount": rprice(total_base * rng.uniform(0.004, 0.012))})
        if rng.random() < 0.15:
            charges.append({"description": "Loading & unloading (supplier billed)", "treatment": "bill",
                            "charge_account_id": A["carriage_in"], "st_taxable": True,
                            "wht_taxable": False, "amount": rprice(rng.uniform(5_000, 40_000))})
        if rng.random() < 0.12:
            charges.append({"description": "Clearing agent — port charges", "treatment": "expense",
                            "charge_account_id": A["clearing"], "st_taxable": False,
                            "amount": rprice(rng.uniform(15_000, 90_000))})
        for ch in charges:
            ch.update({"scope": "general", "distribution": "pro_rata_value"})
            if ch["treatment"] != "bill":
                ch["st_taxable"] = ch["wht_taxable"] = False
        absorb = sum(c["amount"] for c in charges if c["treatment"] == "absorb")
        bill = sum(c["amount"] for c in charges if c["treatment"] == "bill")
        expense = sum(c["amount"] for c in charges if c["treatment"] == "expense")
        st_charges = sum(c["amount"] for c in charges if c["treatment"] == "bill" and c["st_taxable"])
        effective = r2(total_base + per_item_freight + absorb - gdisc)
        tax = r2(tax_lines) if line_tax else r2((effective + st_charges) * TAX / 100)
        wht_pct = 4.5 if supplier["wht"] and rng.random() < 0.8 else 0
        wht = r2(effective * wht_pct / 100)
        net = r2(effective + bill + tax - wht)
        body = self.post_json("/inventory/purchase-invoice/save", {
            "supplier_id": supplier["id"], "invoice_date": d.isoformat(),
            "purchase_order_id": po_id,
            "discount_mode": "individual" if line_disc else "general",
            "expenses_mode": "general", "tax_mode": "individual" if line_tax else "general",
            "global_discount_pct": gdisc_pct, "global_discount_value": gdisc,
            "global_commission": 0, "global_freight": 0, "global_loading": 0,
            "global_sales_tax_pct": 0 if line_tax else TAX,
            "global_withholding_tax_pct": wht_pct, "apply_withholding_tax": bool(wht_pct),
            "subtotal": sub, "total_discount": r2(sub - total_base + gdisc),
            "total_expenses": r2(absorb + bill + expense + per_item_freight),
            "total_tax": tax, "total_withholding_tax": wht,
            "net_payable": net, "total_amount": net,
            "charges": charges, "items": items, "action": "approve"}, "purchase_invoice")
        for p, q, _, _ in lines:
            self.stock[p["id"]] += q
        self.ap[supplier["id"]].append([d, net])
        self.m["input_tax"] += tax
        self.m["wht_payable"] += wht
        self.m["accrued_charges"] += expense
        if not wht and not gdisc and not line_disc and not absorb and not per_item_freight:
            self.recent_purchases.append((d, body["id"], supplier))

    def restock_if_short(self, d):
        """An emergency order when a fast line is nearly out."""
        short = [p for p in self.products
                 if self.stock[p["id"]] + self.on_order.get(p["id"], 0) < p["target"] * 0.08]
        if short and self.rng.random() < 0.5:
            cat = short[0]["cat"]
            s = self.rng.choice([s for s in self.suppliers if s["cat"] == cat])
            self.purchase_invoice(d, s, [(p, q, pr, None) for p, q, pr in self._purchase_lines(s)])

    # ── selling ───────────────────────────────────────────────────

    def _pick_customer(self):
        rng = self.rng
        r = rng.random()
        if r < 0.36:
            return self.walkin
        kind = "project" if r < 0.44 else "installer" if r < 0.60 else "dealer"
        pool = [c for c in self.customers if c["kind"] == kind]
        return rng.choices(pool, weights=[c["weight"] for c in pool])[0]

    def _basket(self, kind):
        rng = self.rng
        P = self.P
        if kind == "retail":
            if rng.random() < 0.3:
                return [(rng.choice(self.by_cat["bos"]), rng.randint(1, 6))]
            kw = rng.choice([3, 5, 6, 8, 10])
            items = [(rng.choice(self.by_cat["panel"]), kw * 1000 // 560 + 1)]
            if rng.random() < 0.7:
                items.append((rng.choice([P["INV-KN-5K"], P["INV-IX-6K"], P["INV-GW-6K"]]), 1))
            if rng.random() < 0.4:
                items.append((P["BAT-NR-200"], rng.choice([2, 4])))
            if rng.random() < 0.6:
                items.append((P["STR-GI-4"], max(1, items[0][1] // 4)))
            if rng.random() < 0.5:
                items.append((P["BOS-MC4"], rng.choice([4, 6, 10])))
            if rng.random() < 0.3:
                items.append((P["CBL-DC-6"], 1))
            return items
        if kind == "project":
            kw = rng.choice([20, 30, 40, 50, 75, 100])
            n_panels = kw * 1000 // 575 + 1
            inv = rng.choice([P["INV-SL-15K"], P["INV-HW-10K"], P["INV-GW-10K"]])
            n_inv = max(1, kw // (15 if inv["sku"] == "INV-SL-15K" else 10))
            items = [(rng.choice(self.by_cat["panel"]), n_panels), (inv, n_inv),
                     (P["STR-L2-6"], max(1, n_panels // 6)),
                     (P["CBL-DC-6"], max(1, kw // 10)), (P["CBL-AC-10"], max(1, kw // 40)),
                     (P["BOS-MC4"], n_panels // 2), (P["BOS-DCB-32"], n_inv * 2),
                     (P["BOS-SPD"], n_inv), (P["BOS-ERTH"], 1 + kw // 50),
                     (P["BOS-DB-PV"], n_inv)]
            if rng.random() < 0.4:
                items.append((P["MTR-NET-3P"], 1))
            if rng.random() < 0.3:
                items.append((rng.choice([P["BAT-PY-5K"], P["BAT-DY-5K"]]), rng.choice([2, 4, 6])))
            if rng.random() < 0.35:
                items = items[:rng.randint(2, len(items))]
            return items
        qty = {"panel": lambda p: rng.randint(10, 40), "inverter": lambda p: rng.randint(1, 3),
               "battery": lambda p: rng.randint(1, 4), "structure": lambda p: rng.randint(2, 8),
               "bos": lambda p: rng.randint(20, 120) if p["sku"] == "BOS-MC4" else rng.randint(2, 30)}
        if kind == "installer":
            return [(p, qty[p["cat"]](p)) for p in rng.sample(self.products, rng.randint(2, 5))]
        # dealer: stock-up orders
        dq = {"panel": lambda p: rng.choice([36, 72, 108, 144]), "inverter": lambda p: rng.randint(2, 8),
              "battery": lambda p: rng.randint(2, 8), "structure": lambda p: rng.randint(5, 20),
              "bos": lambda p: rng.randint(100, 400) if p["sku"] == "BOS-MC4" else rng.randint(10, 60)}
        items = []
        for cat in rng.sample(["panel", "inverter", "battery", "structure", "bos"], rng.randint(1, 4)):
            p = rng.choice(self.by_cat[cat])
            items.append((p, dq[cat](p)))
        return items

    def _price(self, p, kind):
        rng = self.rng
        factor = {"retail": rng.uniform(0.99, 1.03), "dealer": rng.uniform(0.95, 0.99),
                  "project": rng.uniform(0.96, 1.01), "installer": rng.uniform(0.97, 1.0)}[kind]
        return rprice(p["price"] * factor)

    def sale(self, d):
        rng = self.rng
        cust = self._pick_customer()
        merged = {}
        for p, q in self._basket(cust["kind"]):
            merged[p["id"]] = (p, merged.get(p["id"], (p, 0))[1] + int(q))
        wanted = [(p, q, self._price(p, cust["kind"])) for p, q in merged.values() if q > 0]
        # Dealers and project clients often place an order first.
        if cust["kind"] in ("dealer", "project") and rng.random() < 0.3:
            self.sales_order(d, cust, wanted)
            return
        lines = [(p, min(q, int(self.stock[p["id"]])), pr, None) for p, q, pr in wanted]
        lines = [ln for ln in lines if ln[1] > 0]
        if lines:
            self.sales_invoice(d, cust, lines)

    def sales_order(self, d, cust, wanted):
        rng = self.rng
        sub = r2(sum(q * pr for _, q, pr in wanted))
        tax = r2(sub * TAX / 100)
        body = self.post_json("/inventory/sales/save", {
            "customer_id": cust["id"], "order_date": d.isoformat(),
            "expected_date": (d + timedelta(days=7)).isoformat(),
            "tax_mode": "general", "global_sales_tax_pct": TAX,
            "notes": rng.choice(["Customer PO received by email", "Advance discussed — on credit terms",
                                 "Deliver in two lots", "Site delivery required"]),
            "subtotal": sub, "total_tax": tax, "total_amount": r2(sub + tax),
            "items": [{"product_id": p["id"], "description": p["name"], "quantity": q,
                       "unit": p["unit"], "unit_price": pr, "sales_tax_pct": 0,
                       "total_before_discount": r2(q * pr), "total_after_discount": r2(q * pr),
                       "total_price": r2(q * pr)} for p, q, pr in wanted],
            "action": "approve"}, "sales_order")
        from inventory_app.models.sales_order import InvSalesOrderItem
        rows = self.query(lambda: [(i.id, i.product_id, float(i.quantity), float(i.unit_price))
                                   for i in InvSalesOrderItem.query.filter_by(so_id=body["id"]).all()])
        byp = {p["id"]: p for p, _, _ in wanted}
        self.schedule(d + timedelta(days=rng.randint(2, 9)), "so",
                      {"so": body["id"], "cust": cust, "tries": 0,
                       "items": [{"order_item": oid, "p": byp[pid], "qty": q, "price": pr}
                                 for oid, pid, q, pr in rows]})

    def bill_due_orders(self, d):
        due = sorted(x for x in self.pending if x[0] <= d)
        self.pending = [x for x in self.pending if x[0] > d]
        for _, _, kind, job in due:
            if kind == "po":
                lines = [(it["p"], it["qty"], it["price"], it["order_item"])
                         for it in job["items"] if it["qty"] > 0]
                for it in job["items"]:
                    self.on_order[it["p"]["id"]] = max(0, self.on_order.get(it["p"]["id"], 0) - it["qty"])
                if lines:
                    self.purchase_invoice(d, job["supplier"], lines, po_id=job["po"])
                continue
            # A sales order ships what is in stock; the rest follows later.
            lines, rest = [], []
            for it in job["items"]:
                q = min(it["qty"], int(self.stock[it["p"]["id"]]))
                if q > 0:
                    lines.append((it["p"], q, it["price"], it["order_item"]))
                if it["qty"] - q > 0:
                    rest.append(dict(it, qty=it["qty"] - q))
            if lines:
                self.sales_invoice(d, job["cust"], lines, so_id=job["so"])
            if rest and job["tries"] < 3:
                self.schedule(d + timedelta(days=self.rng.randint(6, 15)), "so",
                              dict(job, items=rest, tries=job["tries"] + 1))

    def sales_invoice(self, d, cust, lines, so_id=None):
        """lines: (product, qty, price, order item id or None)."""
        rng = self.rng
        A = self.acc
        kind = cust["kind"]
        line_disc = kind in ("dealer", "installer") and rng.random() < 0.4
        line_tax = kind == "installer" and rng.random() < 0.5
        gdisc_pct = 0 if line_disc else {"retail": 0, "installer": rng.choice([0, 0, 1, 2]),
                                         "dealer": rng.choice([0, 1, 2, 3]),
                                         "project": rng.choice([0, 2, 3, 5])}[kind]
        label = self.labels["retail" if kind == "retail" else
                            "project" if kind == "project" else "dealer"]
        items, tax_lines = [], 0.0
        for p, q, pr, oid in lines:
            before = r2(q * pr)
            dpct = rng.choice([0, 1, 2, 3]) if line_disc else 0
            after = r2(before * (1 - dpct / 100))
            rate = LINE_TAX[p["cat"]] if line_tax else 0
            tax_lines += r2(after * rate / 100)
            items.append({"product_id": p["id"], "quantity": q, "unit_price": pr,
                          "description": p["name"], "unit": p["unit"], "discount_pct": dpct,
                          "discount_amount": r2(before - after), "label_id": label,
                          "delivery": 0, "installation": 0, "sales_tax_pct": rate,
                          "total_before_discount": before, "total_after_discount": after,
                          "source_order_id": so_id, "source_order_item_id": oid})
        sub = r2(sum(it["total_before_discount"] for it in items))
        disc = r2(sub - sum(it["total_after_discount"] for it in items)) if line_disc \
            else r2(sub * gdisc_pct / 100)
        charges = []
        if kind == "project":
            if rng.random() < 0.6:
                charges.append({"description": "Installation & commissioning", "treatment": "bill",
                                "charge_account_id": A["install_income"], "st_taxable": False,
                                "wht_taxable": True, "amount": rprice(sub * rng.uniform(0.03, 0.06))})
            if rng.random() < 0.5:
                charges.append({"description": "Delivery to site", "treatment": "bill",
                                "charge_account_id": A["delivery_income"], "st_taxable": True,
                                "wht_taxable": True, "amount": rprice(rng.uniform(15_000, 60_000))})
            if rng.random() < 0.3:
                charges.append({"description": "Crane hire at site (our cost)", "treatment": "expense",
                                "charge_account_id": A["freight"],
                                "amount": rprice(rng.uniform(12_000, 45_000))})
        elif kind == "dealer":
            if rng.random() < 0.25:
                charges.append({"description": "Delivery charges", "treatment": "bill",
                                "charge_account_id": A["delivery_income"], "st_taxable": True,
                                "wht_taxable": False, "amount": rprice(rng.uniform(3_000, 25_000))})
            elif rng.random() < 0.12:
                charges.append({"description": "Delivery (included in price)", "treatment": "absorb",
                                "charge_account_id": A["delivery_income"],
                                "amount": rprice(rng.uniform(3_000, 15_000))})
        elif kind == "retail" and rng.random() < 0.15:
            charges.append({"description": "Home delivery", "treatment": "bill",
                            "charge_account_id": A["delivery_income"], "st_taxable": True,
                            "wht_taxable": False, "amount": rng.choice([1500, 2500, 3500, 5000])})
        for ch in charges:
            ch.update({"scope": "general", "distribution": "pro_rata_value", "tax_base": "after_discount"})
            if ch["treatment"] != "bill":
                ch["st_taxable"] = ch["wht_taxable"] = False
        pools = defaultdict(float)
        for ch in charges:
            pools[ch["treatment"]] += ch["amount"]
            if ch["treatment"] == "bill":
                pools["st"] += ch["amount"] if ch["st_taxable"] else 0
                pools["wht"] += ch["amount"] if ch["wht_taxable"] else 0
        effective = r2(sub + pools["absorb"])
        st_base = r2(effective - disc + pools["st"])
        wht_base = r2(effective - disc + pools["wht"])
        tax = r2(tax_lines) if line_tax else r2(st_base * TAX / 100)
        further = (not cust["registered"]) and kind != "project" and rng.random() < 0.6
        ft = r2(st_base * FURTHER / 100) if further else 0.0
        wht_pct = 5.5 if kind == "project" and rng.random() < 0.7 else 0
        wht = r2(wht_base * wht_pct / 100)
        total = r2(effective - disc + pools["bill"] + tax + ft - wht)
        body = self.post_json("/inventory/invoices/save", {
            "customer_id": cust["id"], "invoice_date": d.isoformat(), "label_id": label,
            "sales_order_id": so_id,
            "discount_mode": "individual" if line_disc else "general",
            "charges_mode": "general", "tax_mode": "individual" if line_tax else "general",
            "global_discount_pct": gdisc_pct, "global_discount_value": 0 if line_disc else disc,
            "global_delivery": 0, "global_installation": 0,
            "global_sales_tax_pct": 0 if line_tax else TAX,
            "further_tax_pct": FURTHER if further else 0, "apply_further_tax": further,
            "withholding_tax_pct": wht_pct, "apply_withholding_tax": bool(wht_pct),
            "subtotal": sub, "total_discount": disc, "total_charges": pools["bill"],
            "total_tax": tax, "total_further_tax": ft, "total_withholding_tax": wht,
            "total_amount": total, "charges": charges, "items": items,
            "action": "approve"}, "sales_invoice")
        for p, q, _, _ in lines:
            self.stock[p["id"]] -= q
        self.m["output_tax"] += tax
        self.m["further_tax"] += ft
        self.m["accrued_charges"] += pools["expense"]
        self.ar[cust["id"]].append([d, total])
        if cust is self.walkin:
            self.cash_sales_today += total
        elif not line_disc and not line_tax and not ft and not wht and not charges:
            self.recent_sales.append((d, body["id"], cust, gdisc_pct))

    # ── returns and stock vouchers ────────────────────────────────

    @staticmethod
    def _take_newest(q, amount):
        while amount > 0.004 and q:
            if q[-1][1] <= amount + 0.004:
                amount -= q[-1][1]
                q.pop()
            else:
                q[-1][1] = r2(q[-1][1] - amount)
                amount = 0

    @staticmethod
    def _take_oldest(q, amount):
        while amount > 0.004 and q:
            if q[0][1] <= amount + 0.004:
                amount -= q[0][1]
                q.popleft()
            else:
                q[0][1] = r2(q[0][1] - amount)
                amount = 0

    def sales_return(self, d):
        from inventory_app.models.invoice import InvInvoiceItem
        rng = self.rng
        while self.recent_sales and (d - self.recent_sales[0][0]).days > 25:
            self.recent_sales.popleft()
        cands = [s for s in self.recent_sales if (d - s[0]).days >= 2]
        if not cands:
            return
        _, inv_id, cust, disc_pct = rng.choice(cands)

        def pick():
            it = rng.choice(InvInvoiceItem.query.filter_by(invoice_id=inv_id).all())
            return it.id, it.product_id, float(it.quantity), float(it.unit_price), it.description
        item_id, pid, oq, price, desc = self.query(pick)
        qty = max(1, int(oq * rng.uniform(0.05, 0.3)))
        value = r2(qty * price)
        disc = r2(value * disc_pct / 100)
        tax = r2((value - disc) * TAX / 100)
        net = r2(value - disc + tax)
        if net > sum(a for _, a in self.ar[cust["id"]]):
            return  # already paid up: a return now would be a refund, not a credit
        self.post_json("/invoicing/sales-return/save", {
            "original_invoice_id": inv_id, "customer_id": cust["id"], "date": d.isoformat(),
            "notes": rng.choice(["Damaged in transit", "Wrong model delivered",
                                 "Customer cancelled part of order", "Warranty replacement — unit returned"]),
            "gross_return_value": value, "total_discount": disc, "total_charges": 0,
            "total_tax": tax, "net_return_amount": net,
            "items": [{"product_id": pid, "invoice_item_id": item_id, "description": desc,
                       "original_quantity": oq, "max_returnable_qty": oq,
                       "current_return_qty": qty, "unit_price": price,
                       "net_return_value": net}],
            "action": "approve"}, "sales_return")
        self.stock[pid] += qty
        self.m["output_tax"] -= tax
        self._take_newest(self.ar[cust["id"]], net)
        self.recent_sales = deque(s for s in self.recent_sales if s[1] != inv_id)

    def purchase_return(self, d):
        from inventory_app.models.purchase_invoice import InvPurchaseInvoiceItem
        rng = self.rng
        while self.recent_purchases and (d - self.recent_purchases[0][0]).days > 30:
            self.recent_purchases.popleft()
        cands = [s for s in self.recent_purchases if (d - s[0]).days >= 2]
        if not cands:
            return
        _, inv_id, sup = rng.choice(cands)

        def pick():
            it = rng.choice(InvPurchaseInvoiceItem.query.filter_by(invoice_id=inv_id).all())
            return it.product_id, float(it.quantity), float(it.unit_price), float(it.sales_tax_pct or 0)
        pid, oq, price, rate = self.query(pick)
        qty = max(1, int(oq * rng.uniform(0.02, 0.1)))
        if qty > self.stock[pid]:
            return
        value = r2(qty * price)
        tax = r2(value * (rate or TAX) / 100)
        net = r2(value + tax)
        if net > sum(a for _, a in self.ap[sup["id"]]):
            return
        self.post_json("/inventory/purchase-return/save", {
            "original_invoice_id": inv_id, "supplier_id": sup["id"], "date": d.isoformat(),
            "notes": rng.choice(["Cracked glass on arrival", "Short-dated batteries rejected",
                                 "Wrong specification supplied", "Failed incoming inspection"]),
            "gross_return_value": value, "total_discount": 0, "total_expenses": 0,
            "total_tax": tax, "net_return_amount": net,
            "items": [{"product_id": pid, "original_quantity": oq, "max_returnable_qty": oq,
                       "current_return_qty": qty, "unit_price": price,
                       "net_return_value": net}],
            "action": "approve"}, "purchase_return")
        self.stock[pid] -= qty
        self.m["input_tax"] -= tax
        self._take_newest(self.ap[sup["id"]], net)
        self.recent_purchases = deque(s for s in self.recent_purchases if s[1] != inv_id)

    def stock_voucher(self, d):
        rng = self.rng
        if rng.random() < 0.5:
            p = rng.choice(self.by_cat["panel"])
            qty = rng.randint(1, 3)
            if self.stock[p["id"]] < qty:
                return
            self.post_form("/inventory/vouchers/scrap", {
                "date": d.isoformat(), "reason": rng.choice(["Glass cracked during handling",
                                                             "Hail damage in yard", "Transit breakage"]),
                "label_id": self.labels["retail"], "charge_account_id": "", "status": "approved",
                "product_id[]": [str(p["id"])], "qty[]": [str(qty)]}, "scrap")
        else:
            p = rng.choice([self.P["CBL-DC-6"], self.P["BOS-MC4"], self.P["BOS-DCB-32"]])
            qty = 1 if p["sku"] == "CBL-DC-6" else rng.randint(4, 20)
            if self.stock[p["id"]] < qty:
                return
            self.post_form("/inventory/vouchers/consumption", {
                "department": rng.choice(["Showroom", "Warehouse", "Demo Rig"]),
                "reason": rng.choice(["Showroom demo installation", "Warehouse rewiring",
                                      "Testing bench for returns"]),
                "date": d.isoformat(), "label_id": self.labels["retail"],
                "charge_account_id": "", "status": "approved",
                "product_id[]": [str(p["id"])], "qty[]": [str(qty)]}, "consumption")
        self.stock[p["id"]] -= qty

    # ── money ─────────────────────────────────────────────────────

    def voucher(self, vtype, d, cb, rows, kind, label=None):
        """rows: (account id, amount, description, label id)."""
        rng = self.rng
        data = {"action": "approve", "voucher_type": vtype,
                "voucher_date": f"{d.isoformat()}T{rng.randint(9, 18):02d}:{rng.choice(['00', '15', '30', '45'])}",
                "cash_bank_account_id": str(cb),
                "account_id[]": [str(a) for a, _, _, _ in rows],
                "description[]": [t for _, _, t, _ in rows],
                "debit[]": [f"{amt:.2f}" if vtype in ("CPV", "BPV") else "" for _, amt, _, _ in rows],
                "credit[]": [f"{amt:.2f}" if vtype in ("CRV", "BRV") else "" for _, amt, _, _ in rows],
                "label_id[]": [str(lb or "") for _, _, _, lb in rows]}
        if label:
            data["label_id"] = str(label)
        self.post_form("/accounting/vouchers", data, kind)

    def jv(self, d, narration, rows):
        """rows: (account id, debit, credit, description)."""
        self.post_form("/accounting/vouchers", {
            "action": "approve", "voucher_type": "JV",
            "voucher_date": f"{d.isoformat()}T17:00", "cash_bank_account_id": "",
            "notes": narration,
            "account_id[]": [str(a) for a, _, _, _ in rows],
            "description[]": [t for _, _, _, t in rows],
            "debit[]": [f"{dr:.2f}" if dr else "" for _, dr, _, _ in rows],
            "credit[]": [f"{cr:.2f}" if cr else "" for _, _, cr, _ in rows],
            "label_id[]": ["" for _ in rows]}, "journal_voucher")

    def walkin_receipt(self, d):
        amt = r2(self.cash_sales_today)
        self.cash_sales_today = 0.0
        if amt <= 0:
            return
        self.voucher("CRV", d, self.acc["cash"],
                     [(self.walkin["acct"], amt, f"Counter cash sales {d:%d %b %Y}", self.labels["retail"])],
                     "customer_receipt", label=self.labels["retail"])
        self._take_oldest(self.ar[self.walkin["id"]], amt)
        self.cash += amt

    def customer_receipts(self, d):
        rng = self.rng
        for c in self.customers:
            if d < c["next_pay"]:
                continue
            c["next_pay"] = d + timedelta(days=int(c["cycle"] * rng.uniform(0.7, 1.3)))
            q = self.ar[c["id"]]
            due = sum(a for when, a in q if (d - when).days >= c["terms"] * rng.uniform(0.6, 1.1))
            if due < 1000:
                continue
            amt = min(round(due * rng.choice([1, 1, 1, 0.9, 0.75, 0.6]), -2), r2(sum(a for _, a in q)))
            if amt <= 0:
                continue
            # Big balances often arrive as two cheques.
            if amt >= 4_000_000 and rng.random() < 0.5:
                first = round(amt * 0.6, -2)
                parts = [first, r2(amt - first)]
            else:
                parts = [amt]
            for part in parts:
                bank = self.acc["bank"] if rng.random() < 0.7 else self.acc["bank2"]
                how = rng.choice(["Cheque received", "Online transfer (IBFT)",
                                  "Pay order deposited", "RAAST transfer"])
                self.voucher("BRV", d, bank, [(c["acct"], part, f"{how} — {c['name']}", None)],
                             "customer_receipt")
                self._take_oldest(q, part)
                self.bank += part

    def supplier_payments(self, d):
        rng = self.rng
        for s in self.suppliers:
            if d < s["next_pay"]:
                continue
            s["next_pay"] = d + timedelta(days=s["cycle"])
            q = self.ap[s["id"]]
            due = sum(a for when, a in q if (d - when).days >= min(s["terms"], 21) * rng.uniform(0.4, 1.0))
            if due < 1000:
                continue
            amt = min(r2(due), max(0.0, self.bank - 8_000_000))
            if amt < 50_000:
                continue
            if amt < due:
                amt = round(amt, -3)
            how = rng.choice(["Online payment", "Cheque issued", "Pay order issued", "RTGS transfer"])
            self.voucher("BPV", d, self.acc["bank"], [(s["acct"], amt, f"{how} — {s['name']}", None)],
                         "supplier_payment")
            self._take_oldest(q, amt)
            self.bank -= amt

    def _cpv(self, d, acct, amt, text, label=None):
        amt = round(amt, -1)
        if amt <= 0 or self.cash - amt < 100_000:
            return
        self.voucher("CPV", d, self.acc["cash"], [(acct, amt, text, label)], "expense_payment")
        self.cash -= amt

    def _bpv(self, d, rows):
        rows = [(a, round(v, 2), t, lb) for a, v, t, lb in rows if round(v, 2) > 0]
        if not rows:
            return
        self.voucher("BPV", d, self.acc["bank"], rows, "expense_payment")
        self.bank -= sum(v for _, v, _, _ in rows)

    def daily_expenses(self, d):
        rng = self.rng
        A = self.acc
        draw = self.draw
        for _ in range(draw("fuel", 300, d)):
            self._cpv(d, A["freight"], rng.uniform(4_000, 18_000),
                      rng.choice(["Delivery van fuel", "Loader rickshaw fare", "Shehzore fuel — site delivery",
                                  "Toll and parking — deliveries"]), self.labels["dealer"])
        for _ in range(draw("freight", 230, d)):
            self._cpv(d, A["freight"], rng.uniform(6_000, 45_000),
                      rng.choice(["Goods transport to site", "Mazda hire — project delivery",
                                  "Courier — spare parts", "Freight to Gujranwala dealer"]),
                      rng.choice([self.labels["project"], self.labels["dealer"]]))
        for _ in range(draw("office", 100, d)):
            self._cpv(d, A["office"], rng.uniform(1_500, 12_000),
                      rng.choice(["Stationery and printing", "Tea, milk and sugar", "Printer toner",
                                  "Water dispenser bottles", "Cleaning supplies"]))
        for _ in range(draw("misc", 230, d)):
            self._cpv(d, A["other"], rng.uniform(1_000, 9_000),
                      rng.choice(["Staff refreshment", "Generator diesel", "Minor repairs — showroom",
                                  "Courier charges", "Labour — loading/unloading", "Security guard overtime"]))

    def _once(self, tag):
        if tag in self.done_tags:
            return False
        self.done_tags.add(tag)
        return True

    def month_events(self, d):
        rng = self.rng
        A = self.acc
        ym = f"{d:%Y%m}"
        if self._once(f"rent{ym}"):
            self._bpv(d, [(A["rent"], 650_000, f"Showroom rent — Hall Road, {d:%B %Y}", self.labels["retail"]),
                          (A["rent"], 280_000, f"Warehouse rent — Ferozepur Road, {d:%B %Y}", None)])
        if d.day >= 10 and self._once(f"util{ym}"):
            summer = d.month in (5, 6, 7, 8, 9)
            self._bpv(d, [(A["utilities"], rng.uniform(180_000, 260_000) if summer else rng.uniform(90_000, 140_000),
                           f"LESCO electricity — showroom, {d:%b %Y}", self.labels["retail"])])
            self._bpv(d, [(A["utilities"], rng.uniform(70_000, 120_000) if summer else rng.uniform(40_000, 70_000),
                           f"LESCO electricity — warehouse, {d:%b %Y}", None)])
            self._bpv(d, [(A["utilities"], rng.uniform(4_000, 8_000) if summer else rng.uniform(8_000, 22_000),
                           f"SNGPL gas bill, {d:%b %Y}", None)])
            self._bpv(d, [(A["utilities"], 18_500, f"Fibre internet — showroom and warehouse, {d:%b %Y}", None)])
            self._bpv(d, [(A["utilities"], rng.uniform(22_000, 30_000), f"Mobile phone bills, {d:%b %Y}", None)])
        for key, day_, acct, lo, hi, texts, lb in (
            ("mkt1", 8, "marketing", 80_000, 220_000, ["Facebook & Instagram ads"], None),
            ("mkt2", 18, "marketing", 40_000, 160_000, ["Billboard — Canal Road", "Brochures and catalogues",
                                                        "Solar expo stall — Expo Centre", "Google Ads"], None),
            ("mkt3", 25, "marketing", 25_000, 90_000, ["Dealer meet refreshments"], self.labels["dealer"]),
            ("bc1", 6, "bankchg", 2_000, 9_000, ["Bank charges — IBFT / RTGS"], None),
            ("bc2", 13, "bankchg", 1_500, 6_000, ["Cheque book and SMS charges"], None),
            ("bc3", 20, "bankchg", 2_000, 12_000, ["Pay order commission"], None),
            ("bc4", 27, "bankchg", 1_000, 5_000, ["Bank charges — collections"], None),
            ("fee", 15, "fees", 15_000, 120_000, ["Professional tax — Excise & Taxation",
                                                  "Trade licence renewal — LDA",
                                                  "Tax advisor monthly retainer",
                                                  "SECP annual return filing fee"], None),
        ):
            if d.day >= day_ and self._once(f"{key}{ym}"):
                self._bpv(d, [(A[acct], round(rng.uniform(lo, hi), -1), rng.choice(texts), lb)])

        # Last working day of the month: payroll and commission accruals and
        # the sales-tax set-off. All of it is paid early next month.
        last = not any(x.month == d.month and x > d for x in self.work_days if (x - d).days < 7)
        if last:
            payroll = round(rng.uniform(2_350_000, 2_550_000), -2)
            self.jv(d, f"Salaries for {d:%B %Y} — 34 staff",
                    [(A["salary"], payroll, 0, f"Salaries {d:%b %Y}"),
                     (A["salary_payable"], 0, payroll, f"Salaries payable {d:%b %Y}")])
            commission = round(rng.uniform(250_000, 600_000) * SEASON[d.month], -2)
            self.jv(d, f"Dealer and sales-staff commission for {d:%B %Y}",
                    [(A["commission"], commission, 0, f"Commission {d:%b %Y}"),
                     (A["accrued"], 0, commission, f"Commission payable {d:%b %Y}")])
            set_off = r2(max(0.0, min(self.m["input_tax"], self.m["output_tax"])))
            if set_off > 0:
                self.jv(d, f"Input tax adjusted against output tax — {d:%B %Y} sales-tax return",
                        [(A["output_tax"], set_off, 0, "Output tax set off"),
                         (A["input_tax"], 0, set_off, "Input tax adjusted")])
            self.pending_month = {
                "month": d, "payroll": payroll,
                "accrued": r2(commission + self.m["accrued_charges"]),
                "st": r2(self.m["output_tax"] - set_off), "ft": r2(self.m["further_tax"]),
                "wht": r2(self.m["wht_payable"])}
            carry_input = r2(self.m["input_tax"] - set_off)
            self.m = defaultdict(float)
            self.m["input_tax"] = carry_input
        pm = self.pending_month
        if pm and d.month != pm["month"].month:
            mon = f"{pm['month']:%B %Y}"
            if self._once(f"sal{mon}"):
                self._bpv(d, [(A["salary_payable"], pm["payroll"], f"Salaries paid — {mon}", None)])
            if d.day >= 7 and self._once(f"acc{mon}"):
                self._bpv(d, [(A["accrued"], pm["accrued"],
                               f"Commission and accrued transport/clearing bills paid — {mon}", None)])
            if d.day >= 15 and self._once(f"fbr{mon}"):
                self._bpv(d, [(A["output_tax"], pm["st"], f"Sales tax deposited with FBR — {mon} return (CPR)", None),
                              (A["further_tax"], pm["ft"], f"Further tax deposited — {mon}", None)])
                self._bpv(d, [(A["wht_payable"], pm["wht"], f"Income tax withheld from suppliers deposited — {mon}", None)])

    def deposit_cash(self, d):
        surplus = round(self.cash - 600_000, -3)
        if surplus < 100_000:
            return
        bank = self.acc["bank"] if self.rng.random() < 0.6 else self.acc["bank2"]
        self.jv(d, "Cash deposited into bank",
                [(bank, surplus, 0, "Cash deposit slip"),
                 (self.acc["cash"], 0, surplus, "Cash sent to bank")])
        self.cash -= surplus
        self.bank += surplus


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                    help="target database (default: $DATABASE_URL, else the app's dev database)")
    ap.add_argument("--slug", default="samba")
    ap.add_argument("--scale", type=float, default=1.0,
                    help="fraction of the full volume (0.1 = ~750 documents)")
    ap.add_argument("--random-seed", type=int, default=2025)
    ap.add_argument("--company-id", type=int,
                    help="fill this existing (empty) company instead of creating one")
    args = ap.parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app import app
    app.config["WTF_CSRF_ENABLED"] = False
    s = Seeder(app, args.scale, args.slug, random.Random(args.random_seed), args.company_id)
    print("Setting up Samba Private Limited ...", flush=True)
    s.setup()
    s.login()
    print(f"Company id {s.cid}. Posting 1 Jul 2025 – 30 Jun 2026 ...", flush=True)
    s.run()
    total = sum(s.count.values())
    print(f"\nPosted {total} documents in {(time.time() - s.t0) / 60:.1f} min:")
    for k, v in sorted(s.count.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<18} {v:>6}")

    from shared import integrity
    cm = s.ctx()
    try:
        bad = integrity.failures()
    finally:
        cm.pop()
    if bad:
        print("\nBooks integrity FAILED:")
        for b in bad:
            print(f"  {b['label']}: expected {b['expected']} got {b['actual']} ({b['detail']})")
        sys.exit(1)
    print("\nBooks integrity: all checks pass.")


if __name__ == "__main__":
    main()
