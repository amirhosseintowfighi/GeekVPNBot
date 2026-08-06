"""CSV export for the admin panel.

Two decisions that look like superstition and are not:

* The file starts with a UTF-8 BOM. Excel on Windows -- which is what the
  finance side actually uses -- reads a BOM-less UTF-8 CSV as windows-1256
  and renders every Persian heading as mojibake.
* Numbers are written as plain ASCII digits, not Persian ones. Labels are
  Persian, values are machine-readable; a spreadsheet cannot sum \u06f1\u06f2\u06f3.
"""

from __future__ import annotations

import csv
import io

from geekvpn.domain.analytics.dashboard import AnalyticsBundle
from geekvpn.domain.analytics.series import TimeSeries

BOM = "\ufeff"
CONTENT_TYPE = "text/csv; charset=utf-8"

HEADER_METRIC = "\u0634\u0627\u062e\u0635"
HEADER_VALUE = "\u0645\u0642\u062f\u0627\u0631"
HEADER_PREVIOUS = "\u062f\u0648\u0631\u0647\u0654 \u0642\u0628\u0644"
HEADER_CHANGE = "\u062a\u063a\u06cc\u06cc\u0631"
HEADER_DATE = "\u062a\u0627\u0631\u06cc\u062e"
HEADER_SECTION = "\u0628\u062e\u0634"
HEADER_LABEL = "\u0639\u0646\u0648\u0627\u0646"
HEADER_COUNT = "\u062a\u0639\u062f\u0627\u062f"


def _writer() -> tuple[io.StringIO, csv._writer]:
    buffer = io.StringIO()
    buffer.write(BOM)
    return buffer, csv.writer(buffer, lineterminator="\n")


def metrics_csv(bundle: AnalyticsBundle) -> str:
    """The headline cards, one row each."""
    buffer, writer = _writer()
    writer.writerow([HEADER_METRIC, HEADER_VALUE, HEADER_PREVIOUS, HEADER_CHANGE])
    for card in bundle.metrics():
        change = card.change_percent()
        writer.writerow(
            [
                card.label_fa,
                round(card.value, 2),
                round(card.previous, 2),
                "" if change is None else round(change, 2),
            ]
        )
    return buffer.getvalue()


def series_csv(series: TimeSeries) -> str:
    """One time series as date/value pairs.

    The Jalali label is written alongside the ISO timestamp rather than
    instead of it, so the file is both readable and sortable.
    """
    buffer, writer = _writer()
    writer.writerow([HEADER_DATE, series.label_fa, "iso"])
    for point in series.points:
        writer.writerow([point.label_fa, round(point.value, 2), point.at.isoformat()])
    return buffer.getvalue()


def bundle_csv(bundle: AnalyticsBundle) -> str:
    """Everything on the analytics screen, as one sectioned sheet.

    A single file rather than a zip of five: the finance side opens this in
    Excel and scrolls, and a sectioned sheet survives that better than
    multiple tabs nobody notices.
    """
    buffer, writer = _writer()
    writer.writerow([HEADER_SECTION, HEADER_LABEL, HEADER_VALUE, HEADER_PREVIOUS])

    section = "\u0634\u0627\u062e\u0635\u200c\u0647\u0627"
    for card in bundle.metrics():
        writer.writerow([section, card.label_fa, round(card.value, 2), round(card.previous, 2)])

    if bundle.revenue_series is not None:
        section = bundle.revenue_series.label_fa
        for point in bundle.revenue_series.points:
            writer.writerow([section, point.label_fa, round(point.value, 2), ""])

    if bundle.orders_series is not None:
        section = bundle.orders_series.label_fa
        for point in bundle.orders_series.points:
            writer.writerow([section, point.label_fa, round(point.value, 2), ""])

    if bundle.plan_breakdown is not None:
        section = bundle.plan_breakdown.label_fa
        for slice_ in bundle.plan_breakdown.slices:
            writer.writerow(
                [section, slice_.label_fa, round(slice_.value, 2), round(slice_.share, 2)]
            )

    section = "\u0642\u06cc\u0641 \u0641\u0631\u0648\u0634"
    for step in bundle.funnel.steps:
        writer.writerow([section, step.label_fa, step.count, round(step.overall_rate, 2)])

    section = "\u0628\u062e\u0634\u200c\u0628\u0646\u062f\u06cc \u0645\u0634\u062a\u0631\u06cc\u0627\u0646"
    for stat in bundle.segments.stats:
        writer.writerow([section, stat.label_fa, stat.customers, round(stat.share, 2)])

    section = "\u0633\u0631\u0648\u0631\u0647\u0627"
    for node in bundle.fleet.nodes:
        writer.writerow([section, node.name, node.accounts, round(node.load_percent, 2)])

    section = "\u06a9\u0645\u067e\u06cc\u0646\u200c\u0647\u0627"
    for campaign in bundle.campaigns:
        writer.writerow([section, campaign.name_fa, campaign.net_revenue, campaign.discount_given])

    return buffer.getvalue()


def filename_for(days: int) -> str:
    """ASCII filename. Persian in Content-Disposition needs RFC 5987 and
    still breaks in older clients, so the file is named in English and the
    contents are Persian."""
    return f"geekvpn-analytics-{days}d.csv"


__all__ = [
    "BOM",
    "CONTENT_TYPE",
    "bundle_csv",
    "filename_for",
    "metrics_csv",
    "series_csv",
]
