"""
Widget spec + dataframe -> interactive Plotly figure.

One entry point, render_widget(). Every chart type shares the same filter ->
aggregate -> draw pipeline, so a chart type swap in the editor never changes
the numbers, only the picture.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Palette: deep teal anchor, warm counterweight, muted supporting tones.
PALETTE = ["#0F766E", "#B45309", "#3F6296", "#8A6E4B", "#5C7A6B",
           "#9A4A54", "#4B5563", "#2E8B84"]
GRID = "#E3E6EA"
INK = "#101418"
MUTED = "#6B7280"

_GRAIN_FREQ = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}


# ------------------------------------------------------------- filtering

def _coerce(series, value):
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(value, errors="coerce")
    if pd.api.types.is_datetime64_any_dtype(series):
        return pd.to_datetime(value, errors="coerce")
    return value


def apply_filters(df, filters):
    """Apply a list of filter dicts. Unknown columns are skipped, not fatal."""
    out = df
    for f in filters or []:
        col, op, val = f.get("column"), f.get("op"), f.get("value")
        if col not in out.columns or val is None or val == "" or val == []:
            continue
        s = out[col]
        try:
            if op == "in":
                vals = val if isinstance(val, (list, tuple)) else [val]
                out = out[s.isin(vals)]
            elif op == "==":
                out = out[s == _coerce(s, val)]
            elif op == "!=":
                out = out[s != _coerce(s, val)]
            elif op == ">":
                out = out[s > _coerce(s, val)]
            elif op == ">=":
                out = out[s >= _coerce(s, val)]
            elif op == "<":
                out = out[s < _coerce(s, val)]
            elif op == "<=":
                out = out[s <= _coerce(s, val)]
            elif op == "between" and isinstance(val, (list, tuple)) and len(val) == 2:
                lo, hi = _coerce(s, val[0]), _coerce(s, val[1])
                out = out[(s >= lo) & (s <= hi)]
            elif op == "contains":
                out = out[s.astype(str).str.contains(str(val), case=False, na=False)]
        except Exception:
            continue          # a bad filter shouldn't take the dashboard down
    return out


# ----------------------------------------------------------- aggregation

def _grain_series(s, grain):
    """Roll a date column up to day / week / month / quarter / year."""
    s = pd.to_datetime(s, errors="coerce")
    return s.dt.to_period(_GRAIN_FREQ[grain]).dt.to_timestamp()


def aggregate(df, w):
    """Group by x (and colour) and reduce y. Returns a tidy frame: x, [color], value."""
    x, y, color, agg = w.get("x"), w.get("y"), w.get("color"), w.get("agg", "sum")
    d = df.copy()

    if x and w.get("grain") and pd.api.types.is_datetime64_any_dtype(d[x]):
        d[x] = _grain_series(d[x], w["grain"])

    keys = [k for k in (x, color) if k]
    if not keys:
        return pd.DataFrame()

    if agg == "count" or not y:
        g = d.groupby(keys, dropna=False).size().reset_index(name="value")
    elif agg == "nunique":
        g = d.groupby(keys, dropna=False)[y].nunique().reset_index().rename(columns={y: "value"})
    else:
        g = d.groupby(keys, dropna=False)[y].agg(agg).reset_index().rename(columns={y: "value"})

    limit = int(w.get("limit", 15))
    if x and pd.api.types.is_datetime64_any_dtype(g[x]):
        g = g.sort_values(x)
    elif w.get("sort") in ("asc", "desc"):
        if color:
            top = (g.groupby(x)["value"].sum()
                     .sort_values(ascending=w["sort"] == "asc").head(limit).index)
            g = g[g[x].isin(top)]
            order = list(top)
            g[x] = pd.Categorical(g[x], categories=order, ordered=True)
            g = g.sort_values(x)
        else:
            g = g.sort_values("value", ascending=w["sort"] == "asc").head(limit)
    else:
        g = g.head(limit)

    return g


def kpi_value(df, w):
    y, agg = w.get("y"), w.get("agg", "sum")
    if agg == "count" or not y:
        return float(len(df))
    s = pd.to_numeric(df[y], errors="coerce") if y in df.columns else pd.Series(dtype=float)
    if agg == "nunique":
        return float(df[y].nunique()) if y in df.columns else 0.0
    return float(getattr(s, agg)()) if len(s) else 0.0


def format_number(v):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    a = abs(v)
    if a >= 1e7:
        return f"{v/1e7:,.2f} Cr"
    if a >= 1e5:
        return f"{v/1e5:,.2f} L"
    if a >= 1000:
        return f"{v:,.0f}"
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


# --------------------------------------------------------------- drawing

def _style(fig, w):
    fig.update_layout(
        height=w.get("height", 340),
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Public Sans, Segoe UI, sans-serif", size=12, color=INK),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                    title_text="", font=dict(size=11, color=MUTED)),
        colorway=PALETTE,
        hoverlabel=dict(font_size=12),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor="rgba(0,0,0,0)",
                     tickfont=dict(color=MUTED))
    return fig


def render_widget(df, w, global_filters=None):
    """
    Returns (kind, payload):
      ("figure", plotly figure) | ("kpi", (value, label)) |
      ("table", dataframe)      | ("error", message)
    """
    try:
        d = apply_filters(df, global_filters)
        d = apply_filters(d, w.get("filters"))
        if d.empty:
            return "error", "No rows match the current filters."

        t = w.get("type", "bar")
        x, y, color = w.get("x"), w.get("y"), w.get("color")

        if t == "kpi":
            label = w.get("agg", "sum").upper() + (f" of {y}" if y else " of rows")
            return "kpi", (kpi_value(d, w), label)

        if t == "table":
            cols = [c for c in (x, y, color) if c] or list(d.columns)[:8]
            return "table", d[cols].head(int(w.get("limit", 15)))

        if t == "heatmap":
            num = d.select_dtypes(include="number")
            if num.shape[1] < 2:
                return "error", "Needs at least two numeric columns."
            corr = num.corr(numeric_only=True).round(2)
            fig = px.imshow(corr, text_auto=True, aspect="auto",
                            color_continuous_scale=["#B45309", "#F7F8FA", "#0F766E"],
                            zmin=-1, zmax=1)
            fig.update_coloraxes(showscale=False)
            return "figure", _style(fig, w)

        if t == "histogram":
            if not x:
                return "error", "Pick a column to bin."
            fig = px.histogram(d, x=x, color=color, nbins=int(w.get("limit", 15)) * 2)
            return "figure", _style(fig, w)

        if t == "scatter":
            if not (x and y):
                return "error", "Pick an X and a Y column."
            fig = px.scatter(d, x=x, y=y, color=color, opacity=0.75)
            fig.update_traces(marker=dict(size=8, line=dict(width=0)))
            return "figure", _style(fig, w)

        if t == "box":
            if not y:
                return "error", "Pick a numeric column to summarise."
            fig = px.box(d, x=x, y=y, color=color, points=False)
            return "figure", _style(fig, w)

        g = aggregate(d, w)
        if g.empty:
            return "error", "Nothing to plot — check the columns in Edit."

        if t in ("bar", "hbar"):
            if t == "bar":
                fig = px.bar(g, x=x, y="value", color=color, barmode="group")
            else:
                fig = px.bar(g, x="value", y=x, color=color, orientation="h",
                             barmode="group")
            fig.update_traces(marker_line_width=0)
        elif t == "line":
            fig = px.line(g, x=x, y="value", color=color, markers=len(g) < 40)
            fig.update_traces(line=dict(width=2.2))
        elif t == "area":
            fig = px.area(g, x=x, y="value", color=color)
        elif t in ("pie", "donut"):
            fig = px.pie(g, names=x, values="value",
                         hole=0.55 if t == "donut" else 0.0)
            fig.update_traces(textposition="inside", textinfo="percent+label",
                              marker=dict(line=dict(color="#FFFFFF", width=1)))
        else:
            return "error", f"Chart type '{t}' is not supported."

        ylabel = (f"{w.get('agg','sum')} of {y}" if y and w.get("agg") != "count"
                  else "rows")
        fig.update_layout(yaxis_title=ylabel, xaxis_title=None)
        return "figure", _style(fig, w)

    except Exception as e:                     # never let one widget kill the page
        return "error", f"Could not draw this chart: {e}"