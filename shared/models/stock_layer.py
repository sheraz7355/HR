from datetime import datetime

from shared.extensions import db


class StockLayer(db.Model):
    """A parcel of stock on hand at a known unit cost.

    Layers are the source of truth for what stock COSTS. They are never
    derived by replaying the ledger — ``qty_remaining`` is decremented as
    stock is issued, so the pool always reflects what actually happened
    rather than what a valuation method assumes happened.

    The two valuation methods differ in exactly one place: what a RECEIPT
    does.

        FIFO             each receipt opens a new layer.
        weighted average each receipt merges into the single open layer,
                         re-averaging its unit cost.

    Issuing is identical under both: consume layers oldest-first at each
    layer's own cost. Under weighted average there is only ever one open
    layer, so that cost IS the running average.

    This keeps the invariant that makes a method switch safe:

        sum(value_remaining) == StockLedger.running_cost

    which ``assert_invariant`` checks and the costing tests enforce.

    VALUE IS CARRIED, NOT DERIVED. The invariant used to read
    ``sum(qty_remaining * unit_cost)``, and that product cannot hold: the
    ledger accumulates the 2dp totals actually posted to the general ledger,
    while ``unit_cost`` is a 4dp column, so a weighted-average pool re-averaged
    to 4dp is off by up to ``qty * 0.00005`` every time it is re-averaged, and
    an issue posting a 2dp cost is off by up to 0.005 every time it is issued.
    Both accumulate. A pool of 2,834 units in a real database had drifted
    0.13 from its ledger -- thirteen times the tolerance
    ``costing.assert_invariant`` allows -- which is the inventory control
    account quietly untying from COGS.

    So ``value_remaining`` is now the authority and moves only in the same
    posted amounts the ledger moves in, which makes the invariant exact by
    construction rather than approximately true. ``unit_cost`` stays as the
    cost BASIS a unit is issued at; ``unit_cost_effective`` below divides
    carried value by quantity when the engine needs the unrounded figure.
    """

    __tablename__ = "stock_layers"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True)
    product_id = db.Column(db.Integer, nullable=False, index=True)
    # The IN row that opened this layer. Null for layers created by a
    # revaluation (a method switch collapses/carries value, it receives none).
    source_ledger_id = db.Column(db.Integer, db.ForeignKey("stock_ledger.id"), nullable=True)
    unit_cost = db.Column(db.Numeric(16, 4), nullable=False)
    qty_original = db.Column(db.Numeric(16, 4), nullable=False)
    qty_remaining = db.Column(db.Numeric(16, 4), nullable=False, index=True)
    # What the remaining units are worth. Carried rather than computed --
    # see the class docstring. Moves only in amounts the ledger also moves in.
    value_remaining = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    # Which method opened it — audit only; consumption never reads this.
    method = db.Column(db.String(20), nullable=False, default="weighted_average")
    is_revaluation = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    @property
    def unit_cost_effective(self):
        """Carried value over remaining quantity, unrounded.

        What a unit in this layer actually costs. ``unit_cost`` is the 4dp
        rounding of this, and rounding it is what used to make the pool drift.
        """
        from decimal import Decimal
        qty = Decimal(str(self.qty_remaining or 0))
        if qty <= 0:
            return Decimal(str(self.unit_cost or 0))
        return Decimal(str(self.value_remaining or 0)) / qty


class LayerConsumption(db.Model):
    """Which OUT row consumed which layer, and at what cost.

    One row per (issue, layer) pair — an issue spanning three FIFO layers
    writes three rows. This is the audit trail behind every posted cost:
    given a COGS or receivable figure, these rows show exactly which
    purchases backed it.

    Kept append-only. Reversing an issue writes a compensating row rather
    than deleting, so the history of what was posted survives.
    """

    __tablename__ = "layer_consumptions"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True)
    layer_id = db.Column(db.Integer, db.ForeignKey("stock_layers.id"), nullable=False, index=True)
    out_ledger_id = db.Column(db.Integer, db.ForeignKey("stock_ledger.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, nullable=False, index=True)
    qty = db.Column(db.Numeric(16, 4), nullable=False)
    unit_cost = db.Column(db.Numeric(16, 4), nullable=False)
    total_cost = db.Column(db.Numeric(16, 4), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    layer = db.relationship("StockLayer", backref="consumptions")


class StockCostAdjustment(db.Model):
    """A posted cost that changed after the fact, and the journal that moved it.

    Written when a back-dated document, or the reversal of an earlier one,
    re-sequences a product's history so that a later issue (a sale, a
    consumption, a scrap) now draws from different layers. The issue's
    ledger row is re-costed to what it truly cost in date order, and the
    difference is posted here rather than silently: Dr/Cr the account the
    issue originally charged (COGS, the consumption account, the asset)
    against Inventory, dated in the issue's own period when that is still
    open, otherwise in the current open period.
    """

    __tablename__ = "stock_cost_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, index=True)
    product_id = db.Column(db.Integer, nullable=False, index=True)
    ledger_id = db.Column(db.Integer, index=True)
    voucher_type = db.Column(db.String(50), nullable=False)
    voucher_id = db.Column(db.Integer, nullable=False)
    voucher_number = db.Column(db.String(50))
    old_cost = db.Column(db.Numeric(16, 4), nullable=False)
    new_cost = db.Column(db.Numeric(16, 4), nullable=False)
    delta = db.Column(db.Numeric(16, 4), nullable=False)
    # What re-sequenced the history: the back-dated or reversed document.
    trigger = db.Column(db.String(120))
    journal_entry_id = db.Column(db.Integer, db.ForeignKey("journal_entries.id"))
    entry_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
