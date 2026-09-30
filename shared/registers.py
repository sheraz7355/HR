"""Bulk registers (invoice / voucher books): one shared date filter.

Every bulk register filters by exactly one of three modes, driven off the
query string so a filtered view is a shareable URL that survives refresh:

    mode=month   ``month=YYYY-MM``   (default: the current month)
    mode=year    ``period_id=<id>``  (an AccountingPeriod / financial year;
                                      defaults to the one covering today)
    mode=custom  ``from=YYYY-MM-DD`` / ``to=YYYY-MM-DD`` (either side may be
                                      omitted for an open-ended range)

Unparseable values fall back to a sane default rather than 400-ing on a
hand-edited link — a filter is never worth a crash.
"""
import calendar
from calendar import monthrange
from datetime import date, datetime

from shared.models.company_settings import AccountingPeriod


def available_periods():
    """Financial years, newest first, for the filter dropdown."""
    return (AccountingPeriod.query
            .order_by(AccountingPeriod.start_date.desc()).all())


def _default_period(periods, today):
    for p in periods:
        if p.start_date <= today <= p.end_date:
            return p
    return periods[0] if periods else None


def _parse_iso_day(raw):
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError, AttributeError):
        return None


def resolve_register_filter(args, default_mode="month"):
    """(from_date, to_date, ctx) for a bulk register.

    ``from_date``/``to_date`` are dates (either may be None when open-ended);
    ``ctx`` carries everything the template needs to re-render the filter:
    mode, month, period_id, from_str, to_str, label, periods.
    """
    mode = (args.get("mode") or default_mode).strip().lower()
    if mode not in ("month", "year", "custom"):
        mode = default_mode
    today = date.today()
    periods = available_periods()

    from_date, to_date, label = None, None, "All dates"
    month_str = (args.get("month") or "").strip()
    period_id = None
    from_str = (args.get("from") or "").strip()
    to_str = (args.get("to") or "").strip()

    if mode == "month":
        year, month = today.year, today.month
        try:
            y_raw, m_raw = month_str.split("-")
            y, m = int(y_raw), int(m_raw)
            if 1 <= m <= 12 and 1900 <= y <= 2100:
                year, month = y, m
        except ValueError:
            pass
        month_str = f"{year:04d}-{month:02d}"
        from_date = date(year, month, 1)
        to_date = date(year, month, monthrange(year, month)[1])
        label = f"{calendar.month_name[month]} {year}"
    elif mode == "year":
        try:
            period_id = int(args.get("period_id") or 0) or None
        except (TypeError, ValueError):
            period_id = None
        period = next((p for p in periods if p.id == period_id), None)
        if period is None:
            period = _default_period(periods, today)
        if period is not None:
            period_id = period.id
            from_date, to_date = period.start_date, period.end_date
            label = period.period_name or (
                f"{period.start_date:%b %Y} – {period.end_date:%b %Y}")
        else:
            label = "All dates"
    else:
        parsed_from = _parse_iso_day(from_str)
        parsed_to = _parse_iso_day(to_str)
        from_date = parsed_from
        to_date = parsed_to
        from_str = parsed_from.isoformat() if parsed_from else ""
        to_str = parsed_to.isoformat() if parsed_to else ""
        if parsed_from and parsed_to:
            label = (f"{parsed_from:%d %b %Y} – {parsed_to:%d %b %Y}")
        elif parsed_from:
            label = f"From {parsed_from:%d %b %Y}"
        elif parsed_to:
            label = f"Up to {parsed_to:%d %b %Y}"
        else:
            label = "All dates"

    return from_date, to_date, {
        "mode": mode,
        "month": month_str,
        "period_id": period_id,
        "from_str": from_str,
        "to_str": to_str,
        "label": label,
        "periods": periods,
    }


def _day_bounds(from_date, to_date):
    """Datetimes covering whole days, for filtering DateTime columns."""
    start = (datetime.combine(from_date, datetime.min.time())
             if from_date else None)
    end = (datetime.combine(to_date, datetime.max.time())
           if to_date else None)
    return start, end


def apply_date_filter(query, column, from_date, to_date):
    """Constrain a Date/DateTime ``column`` to the resolved range."""
    start, end = _day_bounds(from_date, to_date)
    if start is not None:
        query = query.filter(column >= start)
    if end is not None:
        query = query.filter(column <= end)
    return query
