import json

from flask import Blueprint, render_template, request
from flask_login import login_required

from shared.models.project_label import ProjectLabel
from shared import invoicing_performance as perf
from shared.invoicing_performance import chart as perf_chart
from shared.formatting import format_amount

invoicing_bp = Blueprint("invoicing", __name__, url_prefix="/invoicing")


def _int_arg(name):
    """Query-string integer, or None. A dashboard filter is not worth a 400."""
    raw = (request.args.get(name) or "").strip()
    try:
        return int(raw) or None
    except ValueError:
        return None


@invoicing_bp.route("/")
@login_required
def dashboard():
    """The performance band, and nothing else.

    This route used to also count every document type (suppliers, customers,
    pending orders, unapproved/unpaid sales, returns) and run the payment
    tracking engine for a settlement strip. Those tiles were removed from the
    dashboard, and the queries went with them rather than being left to run on
    every page load for output nobody renders — `pt.feed_rows()` in particular
    walks the whole tracking engine. The tracker itself is still one click away
    in the sidebar, which is where that detail belongs.
    """
    # Both filters come off the query string so a filtered view is a shareable
    # URL that survives a refresh; an unparseable value falls back to the
    # default rather than 500-ing on a hand-edited link.
    years = perf.available_years()
    year = _int_arg("year")
    if year not in years and years:
        year = years[0]

    label_id = _int_arg("label")
    # Archived labels stay selectable: documents already carry them, and
    # dropping one from the list would silently widen the filter to "all".
    labels = ProjectLabel.query.order_by(ProjectLabel.name).all()
    if label_id and not any(l.id == label_id for l in labels):
        label_id = None

    performance = perf.performance(year=year, label_id=label_id)
    geometry = perf_chart(performance)
    return render_template(
        "dashboard/index_invoicing.html",
        perf=performance,
        chart=geometry,
        chart_json=json.dumps(perf.chart_json(performance, geometry,
                                              format_amount)),
        years=years,
        labels=labels,
        sel_year=performance["year"],
        sel_label=label_id,
    )
