"""Revenue / purchases / gross-profit performance for the invoicing dashboard.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
Everything here is read off invoicing *documents* — approved sales invoices,
purchase invoices and their returns. Nothing is read from the ledger and
nothing is posted. That keeps the dashboard honest about its own module, but
it also means "gross profit" here is revenue less purchases, not the finance
module's P&L: there is no opex, payroll or depreciation in these numbers. A
company that buys in one month and sells in the next will show a trough then a
spike, because purchases are recognised when invoiced rather than when the
goods are sold. For a true net profit use the executive dashboard, which ages
real journal lines (`shared/executive_reports.py`).

BASIS: NET OF TAX, NET OF RETURNS
Sales tax, further tax and withholding are collected on behalf of the revenue
authority — they are liabilities, not income — so every figure below is the
goods value: subtotal less discount plus the charges that belong to the
document (delivery/installation on a sale, freight/loading on a purchase).
Approved returns are subtracted from the side they belong to, so a sale that
is invoiced and then returned nets to zero rather than inflating both a
revenue month and nothing else.

UNAPPROVED DOCUMENTS ARE EXCLUDED
An unapproved invoice is a draft; it posts no journal and can still be edited
or deleted. Counting drafts would let the dashboard disagree with the ledger
for reasons the reader cannot see.
"""

import math
from calendar import month_abbr
from datetime import datetime

from inventory_app.models.invoice import InvInvoice
from inventory_app.models.purchase_invoice import InvPurchaseInvoice
from inventory_app.models.purchase_return import InvPurchaseReturn
from inventory_app.models.sales_return import InvSalesReturn

MONTHS = [month_abbr[m].upper() for m in range(1, 13)]

# The four document types, each described once so the aggregation loop below
# stays a loop rather than four near-identical blocks. `sign` is what the
# document does to its side of the business: returns come off.
#   side:   "revenue" | "purchases"
#   date:   the column that decides which month the document lands in
#   parts:  (added..., subtracted...) columns forming the net-of-tax value
#   status: the column and value that mean "approved"
#   label:  the column carrying the project label, or the FK to follow to it
_SOURCES = [
    {
        "model": InvInvoice, "side": "revenue", "sign": 1,
        "date": "invoice_date",
        "add": ("subtotal", "total_charges"), "sub": ("total_discount",),
        "status_col": "voucher_status", "status_val": "approved",
        "label_col": "label_id", "label_via": None,
    },
    {
        "model": InvSalesReturn, "side": "revenue", "sign": -1,
        "date": "return_date",
        "add": ("gross_return_value", "total_charges"), "sub": ("total_discount",),
        "status_col": "status", "status_val": "approved",
        # Returns carry no label of their own, so they inherit the label of the
        # invoice they reverse. Without this a label-filtered view would show
        # the sale but not its return, and overstate that label's revenue.
        "label_col": None, "label_via": (InvInvoice, "original_invoice_id"),
    },
    {
        "model": InvPurchaseInvoice, "side": "purchases", "sign": 1,
        "date": "invoice_date",
        "add": ("subtotal", "total_expenses"), "sub": ("total_discount",),
        "status_col": "status", "status_val": "approved",
        "label_col": "label_id", "label_via": None,
    },
    {
        "model": InvPurchaseReturn, "side": "purchases", "sign": -1,
        "date": "return_date",
        "add": ("gross_return_value", "total_expenses"), "sub": ("total_discount",),
        "status_col": "status", "status_val": "approved",
        "label_col": None, "label_via": (InvPurchaseInvoice, "original_invoice_id"),
    },
]


def _net(row, src):
    """Goods value of one document: additions less deductions, NULLs as zero."""
    total = 0.0
    for col in src["add"]:
        total += float(getattr(row, col, 0) or 0)
    for col in src["sub"]:
        total -= float(getattr(row, col, 0) or 0)
    return total


def _rows(src, start, end, label_id):
    """Approved documents of one type inside [start, end), label-filtered.

    Only the columns the arithmetic needs are selected — a dashboard should
    not pull whole invoice rows (with notes and every tax column) just to add
    up four floats.
    """
    model = src["model"]
    date_col = getattr(model, src["date"])
    # The date column is aliased so the caller can read it back under one name
    # whichever document type this is (invoice_date vs return_date). The alias
    # avoids a leading underscore: SQLAlchemy's Row reserves that namespace
    # for its own API (_mapping, _fields), and a "_when" label collides there.
    q = model.query.with_entities(
        date_col.label("when_at"),
        *[getattr(model, c) for c in src["add"] + src["sub"]])
    q = q.filter(getattr(model, src["status_col"]) == src["status_val"])
    q = q.filter(date_col >= start, date_col < end)
    if label_id:
        if src["label_col"]:
            q = q.filter(getattr(model, src["label_col"]) == label_id)
        else:
            parent, fk = src["label_via"]
            # Correlated subquery rather than a join: the join would have to
            # go through the tenant-scoped parent query and duplicate its
            # filters, and this keeps the label rule in exactly one place.
            q = q.filter(getattr(model, fk).in_(
                parent.query.with_entities(parent.id)
                      .filter(parent.label_id == label_id)))
    return q.all()


def _empty_months():
    return [{"m": m, "name": MONTHS[m - 1],
             "revenue": 0.0, "purchases": 0.0, "gross": 0.0}
            for m in range(1, 13)]


def _totals_for(year, label_id):
    """Twelve months of revenue/purchases/gross for one year."""
    months = _empty_months()
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    for src in _SOURCES:
        for row in _rows(src, start, end, label_id):
            when = row.when_at
            if when is None:
                continue
            months[when.month - 1][src["side"]] += src["sign"] * _net(row, src)
    for slot in months:
        slot["gross"] = slot["revenue"] - slot["purchases"]
    totals = {
        "revenue": sum(s["revenue"] for s in months),
        "purchases": sum(s["purchases"] for s in months),
    }
    totals["gross"] = totals["revenue"] - totals["purchases"]
    # Margin is only meaningful against positive revenue; a company with no
    # sales has no margin, and dividing by a negative (net returns exceeding
    # sales) would print a sign that reads backwards.
    totals["margin"] = (totals["gross"] / totals["revenue"] * 100.0
                        if totals["revenue"] > 0 else None)
    return months, totals


def available_years():
    """Years that actually carry an approved document, newest first.

    Empty when the company has posted nothing — the caller falls back to the
    current year so the page still renders a (zeroed) chart.
    """
    years = set()
    for src in _SOURCES:
        col = getattr(src["model"], src["date"])
        q = (src["model"].query.with_entities(col)
             .filter(getattr(src["model"], src["status_col"]) == src["status_val"])
             .filter(col.isnot(None)))
        for (when,) in q.all():
            if when is not None:
                years.add(when.year)
    return sorted(years, reverse=True)


def performance(year=None, label_id=None):
    """Dashboard payload: the year's monthly series, totals and YoY deltas.

    `label_id` of None/0 means every label (no filter).
    """
    label_id = label_id or None
    if year is None:
        years = available_years()
        # Local year, not UTC: this is the fallback for a company with no
        # documents at all, and "this year" to the person reading the page
        # means their calendar, not the server's.
        year = years[0] if years else datetime.now().year
    months, totals = _totals_for(year, label_id)
    _, prev = _totals_for(year - 1, label_id)

    # Percentage change against the prior year. A prior of zero has no
    # percentage (growth from nothing is undefined, not "infinite"), so the
    # template shows the absolute move instead of a misleading number.
    deltas = {}
    for key in ("revenue", "purchases", "gross"):
        was, now = prev[key], totals[key]
        deltas[key] = ((now - was) / abs(was) * 100.0) if was else None

    peak = max((s["revenue"] for s in months), default=0.0)
    trough = min((s["gross"] for s in months), default=0.0)
    return {
        "year": year, "months": months, "totals": totals,
        "prev": prev, "prev_year": year - 1, "deltas": deltas,
        # The axis has to cover the tallest series and any negative gross.
        "peak": peak, "trough": min(trough, 0.0),
        "label_id": label_id,
    }


# ── CHART GEOMETRY ────────────────────────────────────────────────────────
# Point coordinates are worked out here rather than in the template. Jinja can
# do the arithmetic, but a chart's geometry is exactly the kind of thing that
# needs a test, and a template is the one place in this codebase nothing can
# unit-test. The template stays a renderer: it receives strings and prints
# them.

# The plot box, in viewBox units. The SVG scales to its container, so these are
# proportions rather than pixels; strokes are pinned with non-scaling-stroke so
# a 2px line stays 2px at any width.
VIEW_W, VIEW_H = 720.0, 248.0
PAD_L, PAD_R, PAD_T, PAD_B = 58.0, 14.0, 14.0, 26.0
PLOT_W = VIEW_W - PAD_L - PAD_R
PLOT_H = VIEW_H - PAD_T - PAD_B

# Series render back-to-front, so the one a reader most needs to trace sits on
# top. Gross profit is the answer the chart exists to give, so it goes last.
# `var` is the CSS custom-property suffix the template paints with
# (--s-rev / --s-pur / --s-gp). Naming it here rather than in the template
# keeps the SVG, the legend, the KPI swatches and the hover tooltip reading
# one mapping instead of four copies of the same conditional.
SERIES = [
    {"key": "revenue",   "label": "Revenue",      "slot": 1, "var": "rev"},
    {"key": "purchases", "label": "Purchases",    "slot": 2, "var": "pur"},
    {"key": "gross",     "label": "Gross profit", "slot": 3, "var": "gp"},
]


def _nice_step(span, target_ticks=4):
    """A round gridline step covering `span` in roughly `target_ticks` steps.

    Axis ticks that read 0 / 200,000 / 400,000 are worth the few lines this
    takes; ticks at 0 / 181,250 / 362,500 make a reader do arithmetic to
    compare two points.
    """
    if span <= 0:
        return 1.0
    raw = span / max(target_ticks, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mult * mag:
            return mult * mag
    return 10 * mag


def chart(data):
    """Turn a `performance()` payload into ready-to-print SVG geometry."""
    months = data["months"]
    hi = max([s["revenue"] for s in months] + [s["purchases"] for s in months]
             + [s["gross"] for s in months] + [0.0])
    lo = min([s["gross"] for s in months] + [0.0])
    if hi == lo:
        hi = lo + 1.0
    step = _nice_step(hi - lo)
    top = math.ceil(hi / step) * step
    bottom = math.floor(lo / step) * step
    if top == bottom:
        top = bottom + step

    def y_of(v):
        return PAD_T + PLOT_H * (top - v) / (top - bottom)

    def x_of(i):
        # 12 points across the plot: first on the left edge, last on the right.
        return PAD_L + (PLOT_W * i / 11.0 if len(months) > 1 else PLOT_W / 2)

    ticks = []
    t = bottom
    while t <= top + step / 1000.0:
        ticks.append({"v": t, "y": round(y_of(t), 2)})
        t += step

    series = []
    for spec in SERIES:
        pts = [(round(x_of(i), 2), round(y_of(s[spec["key"]]), 2))
               for i, s in enumerate(months)]
        series.append({
            **spec,
            "points": " ".join(f"{x},{y}" for x, y in pts),
            # The area wash closes onto the zero line, not the bottom of the
            # box: with a negative month the fill would otherwise read as if
            # the value were positive all the way down.
            "area": ("{start} ".format(start=f"{pts[0][0]},{y_of(0):.2f}")
                     + " ".join(f"{x},{y}" for x, y in pts)
                     + f" {pts[-1][0]},{y_of(0):.2f}"),
            "dots": [{"x": x, "y": y, "v": months[i][spec["key"]],
                      "month": months[i]["name"]}
                     for i, (x, y) in enumerate(pts)],
            "last": {"x": pts[-1][0], "y": pts[-1][1]},
        })
    return {
        "view_w": VIEW_W, "view_h": VIEW_H,
        "pad_l": PAD_L, "pad_t": PAD_T, "pad_b": PAD_B,
        "plot_w": PLOT_W, "plot_h": PLOT_H,
        "plot_r": PAD_L + PLOT_W, "plot_b": PAD_T + PLOT_H,
        "zero_y": round(y_of(0), 2),
        "ticks": ticks, "series": series,
        "cols": [{"x": round(x_of(i), 2), "name": s["name"], "i": i}
                 for i, s in enumerate(months)],
        "band": round(PLOT_W / 11.0, 2),
    }


def chart_json(data, geo, fmt):
    """Compact payload for the hover layer.

    The tooltip needs a *formatted* value per point, and formatting is the
    app's job (`shared.formatting.format_amount`), not JavaScript's — sending
    raw floats would mean reimplementing thousands separators and the
    company's decimal preference in the browser and watching the two drift.
    Only what the tooltip reads is included; the SVG already carries the rest.
    """
    return {
        "year": data["year"],
        "view_w": geo["view_w"],
        "cols": [{"x": c["x"], "name": c["name"]} for c in geo["cols"]],
        "series": [{
            "key": s["key"], "label": s["label"], "var": s["var"],
            "dots": [{"x": d["x"], "y": d["y"], "text": fmt(d["v"], 0)}
                     for d in s["dots"]],
        } for s in geo["series"]],
    }
