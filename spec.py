"""
The dashboard contract.

A dashboard is plain JSON. That single decision is what makes the rest work:
the manual editor writes this shape, the AI writes this shape, and the renderer
only ever reads this shape. Nothing else in the app needs to know which of the
two produced a widget.

Widgets are laid out on a 12-column grid, packed left to right in order.
"""

import uuid

CHART_TYPES = [
    "kpi", "bar", "hbar", "line", "area", "pie", "donut",
    "scatter", "histogram", "box", "table", "heatmap",
]

AGGS = ["sum", "mean", "median", "min", "max", "count", "nunique"]

FILTER_OPS = ["in", "==", "!=", ">", ">=", "<", "<=", "between", "contains"]

GRAINS = [None, "day", "week", "month", "quarter", "year"]

WIDTHS = [3, 4, 6, 8, 12]          # columns out of 12
DEFAULT_HEIGHT = 340


def new_id():
    return uuid.uuid4().hex[:8]


def new_widget(**kw):
    w = {
        "id": new_id(),
        "type": "bar",
        "title": "Untitled chart",
        "x": None,
        "y": None,
        "agg": "sum",
        "color": None,
        "grain": None,          # date rollup: day | week | month | quarter | year
        "sort": "desc",
        "limit": 15,
        "filters": [],
        "width": 6,
        "height": DEFAULT_HEIGHT,
        "note": "",
    }
    w.update(kw)
    return w


def new_dashboard(name, dataset=None):
    return {
        "name": name,
        "dataset": dataset,
        "description": "",
        "filters": [],          # global slicers, applied to every widget
        "widgets": [],
        "version": 1,
    }


# ------------------------------------------------------------ validation

def _valid_filter(f, columns):
    return (
        isinstance(f, dict)
        and f.get("column") in columns
        and f.get("op") in FILTER_OPS
    )


def validate_widget(w, columns, numeric_cols):
    """
    Coerce one widget into something renderable.

    Returns (widget, problems). A widget with an unfixable problem is still
    returned so the person can see and repair it in the editor rather than
    having it silently vanish.
    """
    problems = []
    out = new_widget()

    if not isinstance(w, dict):
        return None, ["Widget was not an object."]

    out["id"] = str(w.get("id") or new_id())[:16]
    out["title"] = str(w.get("title") or "Untitled chart")[:120]
    out["note"] = str(w.get("note") or "")[:300]

    t = str(w.get("type", "bar")).lower().strip()
    if t not in CHART_TYPES:
        problems.append(f"Unknown chart type '{t}' — using a bar chart.")
        t = "bar"
    out["type"] = t

    for field in ("x", "y", "color"):
        val = w.get(field)
        if val in (None, "", "None"):
            out[field] = None
        elif val in columns:
            out[field] = val
        else:
            out[field] = None
            problems.append(f"Column '{val}' is not in this dataset ({field}).")

    agg = str(w.get("agg", "sum")).lower()
    out["agg"] = agg if agg in AGGS else "sum"

    # A non-count aggregation needs a numeric measure.
    if out["agg"] not in ("count", "nunique") and out["y"] and out["y"] not in numeric_cols:
        if t in ("bar", "hbar", "line", "area", "pie", "donut", "kpi"):
            out["agg"] = "count"
            problems.append(f"'{out['y']}' is not numeric — counting rows instead.")

    grain = w.get("grain")
    out["grain"] = grain if grain in ("day", "week", "month", "quarter", "year") else None

    out["sort"] = w.get("sort") if w.get("sort") in ("asc", "desc", None) else "desc"

    try:
        out["limit"] = max(1, min(100, int(w.get("limit", 15))))
    except (TypeError, ValueError):
        out["limit"] = 15

    width = w.get("width", 6)
    out["width"] = width if width in WIDTHS else min(WIDTHS, key=lambda c: abs(c - 6))

    try:
        out["height"] = max(160, min(900, int(w.get("height", DEFAULT_HEIGHT))))
    except (TypeError, ValueError):
        out["height"] = DEFAULT_HEIGHT

    out["filters"] = [f for f in (w.get("filters") or []) if _valid_filter(f, columns)]

    # Minimum viable config per chart type.
    if t == "kpi" and not out["y"] and out["agg"] not in ("count",):
        out["agg"] = "count"
    if t in ("bar", "hbar", "line", "area", "pie", "donut", "box") and not out["x"]:
        problems.append("No category column set — pick one in Edit.")
    if t == "scatter" and not (out["x"] and out["y"]):
        problems.append("Scatter needs both an X and a Y column.")
    if t == "histogram" and not out["x"]:
        problems.append("Histogram needs a numeric column.")

    return out, problems


def validate_dashboard(spec, df):
    """Validate a whole spec against the loaded dataframe."""
    columns = list(df.columns)
    numeric_cols = list(df.select_dtypes(include="number").columns)

    if not isinstance(spec, dict):
        return new_dashboard("Untitled"), ["The spec was not an object."]

    out = new_dashboard(str(spec.get("name") or "Untitled dashboard")[:80])
    out["dataset"] = spec.get("dataset")
    out["description"] = str(spec.get("description") or "")[:400]
    out["filters"] = [
        f for f in (spec.get("filters") or []) if _valid_filter(f, columns)
    ]

    problems = []
    for w in (spec.get("widgets") or []):
        widget, probs = validate_widget(w, columns, numeric_cols)
        if widget:
            out["widgets"].append(widget)
            problems += [f"{widget['title']}: {p}" for p in probs]

    return out, problems


# --------------------------------------------------------------- layout

def pack_rows(widgets):
    """Group widgets into rows of at most 12 columns, preserving order."""
    rows, row, used = [], [], 0
    for w in widgets:
        width = w.get("width", 6)
        if used + width > 12 and row:
            rows.append(row)
            row, used = [], 0
        row.append(w)
        used += width
    if row:
        rows.append(row)
    return rows


def move_widget(widgets, widget_id, delta):
    ids = [w["id"] for w in widgets]
    if widget_id not in ids:
        return widgets
    i = ids.index(widget_id)
    j = max(0, min(len(widgets) - 1, i + delta))
    widgets.insert(j, widgets.pop(i))
    return widgets