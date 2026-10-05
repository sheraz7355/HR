from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from shared.extensions import db
from ..models.asset import FixedAsset, AssetCategory, AssetDepreciation
from datetime import date

fa_reports_bp = Blueprint("fa_reports", __name__, url_prefix="/fixed-assets/reports")


@fa_reports_bp.route("/")
@login_required
def index():
    if not current_user.module_access("fixed_assets"):
        return render_template("access_denied.html")
    assets = FixedAsset.query.filter_by(is_active=True)\
        .join(AssetCategory, AssetCategory.id == FixedAsset.category_id)\
        .order_by(AssetCategory.name, FixedAsset.name).all()
    total_cost = sum(a.purchase_cost for a in assets)
    total_dep = sum(a.accumulated_depreciation for a in assets)
    category_summary = {}
    for a in assets:
        cat_name = a.category_obj.name if a.category_obj else "Uncategorized"
        if cat_name not in category_summary:
            category_summary[cat_name] = {"count": 0, "cost": 0, "depreciation": 0}
        category_summary[cat_name]["count"] += 1
        category_summary[cat_name]["cost"] += a.purchase_cost
        category_summary[cat_name]["depreciation"] += a.accumulated_depreciation
    status_summary = {}
    for a in assets:
        s = a.status or "unknown"
        if s not in status_summary:
            status_summary[s] = {"count": 0, "cost": 0}
        status_summary[s]["count"] += 1
        status_summary[s]["cost"] += a.purchase_cost
    fmt = request.args.get("format")
    if fmt:
        return _export_register(fmt, assets, category_summary)
    return render_template("fixed_assets/reports/index.html",
                           assets=assets,
                           total_cost=total_cost,
                           total_dep=total_dep,
                           net_book_value=total_cost - total_dep,
                           category_summary=category_summary,
                           status_summary=status_summary)


def _export_register(fmt, assets, category_summary):
    """Fixed asset register: every active asset with cost, depreciation
    posted to date and net book value; Excel adds the category summary."""
    from shared import report_export as rx
    headers = ["Code", "Asset", "Category", "Purchase date", "Location",
               "Assigned to", "Serial no.", "Method", "Life (yrs)", "Cost",
               "Salvage", "Acc. depreciation", "Net book value", "Status"]
    rows = [[a.asset_code, a.name, a.category_obj.name if a.category_obj else "",
             a.purchase_date, a.location or "", a.assigned_to or "",
             a.serial_number or "", (a.depreciation_method or "").replace("_", " ").title(),
             a.useful_life, float(a.purchase_cost or 0), float(a.salvage_value or 0),
             float(a.posted_depreciation or 0), float(a.net_book_value or 0),
             (a.status or "").title()] for a in assets]
    rows.append(["", f"Total ({len(assets)} assets)", "", "", "", "", "", "", "",
                 sum(r[9] for r in rows), sum(r[10] for r in rows),
                 sum(r[11] for r in rows), sum(r[12] for r in rows), ""])
    kinds = ["plain"] * len(assets) + ["grand"]
    title = "Fixed Asset Register"
    period = f"Active assets as at {date.today():%d %b %Y}"
    if fmt in ("excel", "xlsx"):
        summary = [[name, d["count"], float(d["cost"]), float(d["depreciation"]),
                    float(d["cost"] - d["depreciation"])]
                   for name, d in category_summary.items()]
        buf = rx.build_excel(title, headers, rows, period=period, row_kinds=kinds,
                             col_formats={8: "0"},
                             extra_sheets=[("By category",
                                            ["Category", "Assets", "Cost",
                                             "Acc. depreciation", "Net book value"],
                                            summary)])
        return rx.send_export(buf, "excel", title, date.today())
    return rx.export_table(fmt, title, headers, rows, period=period,
                           row_kinds=kinds, col_formats={8: "0"},
                           file_period=date.today())
