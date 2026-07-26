"""
The canvas: renders a dashboard spec, and edits it in place.

Layout is a 12-column grid packed in widget order. Streamlit has no native
drag-and-drop, so the editor gives each tile move / resize / duplicate / remove
controls, which covers the same ground with fewer moving parts. If you want
true drag-and-drop later, swap pack_rows() for streamlit-elements' dashboard
grid — the spec does not change.
"""

import pandas as pd
import streamlit as st

import charts
import spec as spec_mod
from compat import WIDE

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Public+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Newsreader:opsz,wght@6..72,500&display=swap');

html, body, [class*="css"], .stMarkdown, .stButton, .stSelectbox {
    font-family: 'Public Sans', 'Segoe UI', sans-serif;
}
h1, h2 { font-family: 'Newsreader', Georgia, serif; letter-spacing: -0.01em; }

.block-container { padding-top: 2.2rem; max-width: 1500px; }

.tile {
    background: #FFFFFF;
    border: 1px solid #E3E6EA;
    border-radius: 10px;
    padding: 14px 16px 6px 16px;
    margin-bottom: 10px;
}
.tile-title {
    font-size: 0.82rem; font-weight: 600; letter-spacing: 0.04em;
    text-transform: uppercase; color: #6B7280; margin-bottom: 2px;
}
.tile-note { font-size: 0.78rem; color: #9AA1AB; margin-bottom: 6px; }

/* KPI: figures set in mono so digits line up down a column of cards */
.kpi {
    background: #FFFFFF;
    border: 1px solid #E3E6EA;
    border-left: 3px solid #0F766E;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 10px;
}
.kpi .value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 1.85rem; font-weight: 500; color: #101418;
    font-variant-numeric: tabular-nums; line-height: 1.15;
}
.kpi .label {
    font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.06em;
    color: #6B7280; margin-top: 4px;
}
.empty {
    border: 1px dashed #C9CED6; border-radius: 10px; padding: 34px 20px;
    text-align: center; color: #6B7280;
}
div[data-testid="stMetricValue"] { font-family: 'IBM Plex Mono', monospace; }
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


# ---------------------------------------------------------- global filters

def render_filter_bar(df, spec, key_prefix="gf"):
    """Slicers that apply to every widget on the dashboard."""
    with st.expander(f"Filters ({len(spec.get('filters', []))} active)", expanded=False):
        add_col = st.selectbox(
            "Add a slicer", ["—"] + list(df.columns), key=f"{key_prefix}_add"
        )
        if add_col != "—" and st.button("Add slicer", key=f"{key_prefix}_addbtn"):
            s = df[add_col]
            if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
                f = {"column": add_col, "op": "between", "value": None}
            else:
                f = {"column": add_col, "op": "in", "value": []}
            spec.setdefault("filters", []).append(f)
            st.rerun()

        keep = []
        for i, f in enumerate(spec.get("filters", [])):
            col = f.get("column")
            if col not in df.columns:
                continue
            s = df[col]
            c1, c2 = st.columns([9, 1])
            with c1:
                if pd.api.types.is_datetime64_any_dtype(s):
                    lo, hi = s.min(), s.max()
                    val = st.date_input(col, value=(lo.date(), hi.date()),
                                        key=f"{key_prefix}_{i}")
                    if isinstance(val, tuple) and len(val) == 2:
                        f["op"], f["value"] = "between", [str(val[0]), str(val[1])]
                elif pd.api.types.is_numeric_dtype(s):
                    lo, hi = float(s.min()), float(s.max())
                    if lo == hi:
                        hi = lo + 1
                    cur = f.get("value") or [lo, hi]
                    val = st.slider(col, lo, hi, (float(cur[0]), float(cur[1])),
                                    key=f"{key_prefix}_{i}")
                    f["op"], f["value"] = "between", [val[0], val[1]]
                else:
                    options = sorted(s.dropna().astype(str).unique().tolist())[:500]
                    cur = [v for v in (f.get("value") or []) if v in options]
                    val = st.multiselect(col, options, default=cur,
                                         key=f"{key_prefix}_{i}")
                    f["op"], f["value"] = "in", val
            with c2:
                st.write("")
                if st.button("Remove", key=f"{key_prefix}_rm_{i}"):
                    continue
            keep.append(f)
        spec["filters"] = keep
    return spec.get("filters", [])


# ------------------------------------------------------------- one widget

def _tile_header(w):
    st.markdown(f"<div class='tile-title'>{w.get('title','')}</div>",
                unsafe_allow_html=True)
    if w.get("note"):
        st.markdown(f"<div class='tile-note'>{w['note']}</div>", unsafe_allow_html=True)


def render_one(df, w, global_filters, edit_mode, spec, index, kp="dash"):
    kind, payload = charts.render_widget(df, w, global_filters)

    if kind == "kpi":
        value, label = payload
        st.markdown(
            f"<div class='kpi'><div class='value'>{charts.format_number(value)}</div>"
            f"<div class='label'>{w.get('title') or label}</div></div>",
            unsafe_allow_html=True,
        )
    else:
        with st.container(border=True):
            _tile_header(w)
            if kind == "figure":
                st.plotly_chart(payload, key=f"{kp}_fig_{w['id']}_{index}", **WIDE)
            elif kind == "table":
                st.dataframe(payload, hide_index=True,
                             height=min(w.get("height", 340), 420), **WIDE)
            else:
                st.info(payload)

    if edit_mode:
        widget_controls(df, w, spec, index, kp)


def widget_controls(df, w, spec, index, kp="dash"):
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("Move up", key=f"{kp}_up_{w['id']}", **WIDE):
        spec_mod.move_widget(spec["widgets"], w["id"], -1)
        st.rerun()
    if c2.button("Move down", key=f"{kp}_dn_{w['id']}", **WIDE):
        spec_mod.move_widget(spec["widgets"], w["id"], 1)
        st.rerun()
    if c3.button("Duplicate", key=f"{kp}_cp_{w['id']}", **WIDE):
        clone = dict(w)
        clone["id"] = spec_mod.new_id()
        clone["title"] = w.get("title", "") + " (copy)"
        spec["widgets"].insert(index + 1, clone)
        st.rerun()
    if c4.button("Remove", key=f"{kp}_del_{w['id']}", **WIDE):
        spec["widgets"] = [x for x in spec["widgets"] if x["id"] != w["id"]]
        st.rerun()

    with st.expander("Edit this tile"):
        widget_editor(df, w, spec, kp)


def widget_editor(df, w, spec, kp="dash"):
    """
    Edit one tile. Nothing is written back to the spec until Apply is pressed,
    so an abandoned edit leaves the dashboard exactly as it was.
    """
    cols = ["\u2014"] + list(df.columns)
    grains = ["none", "day", "week", "month", "quarter", "year"]
    sorts = ["desc", "asc", "none"]

    def idx(val):
        return cols.index(val) if val in cols else 0

    with st.form(f"{kp}_form_{w['id']}"):
        title = st.text_input("Title", w.get("title", ""))
        c1, c2, c3 = st.columns(3)
        wtype = c1.selectbox("Chart", spec_mod.CHART_TYPES,
                             index=spec_mod.CHART_TYPES.index(w.get("type", "bar")))
        x = c2.selectbox("Category / X axis", cols, index=idx(w.get("x")))
        y = c3.selectbox("Measure / Y axis", cols, index=idx(w.get("y")))

        c4, c5, c6 = st.columns(3)
        agg = c4.selectbox("Aggregate", spec_mod.AGGS,
                           index=spec_mod.AGGS.index(w.get("agg", "sum")))
        color = c5.selectbox("Split by", cols, index=idx(w.get("color")))
        grain = c6.selectbox("Date rollup", grains,
                             index=grains.index(w.get("grain") or "none"))

        c7, c8, c9 = st.columns(3)
        sort = c7.selectbox("Sort", sorts, index=sorts.index(w.get("sort") or "none"))
        limit = c8.number_input("Show top", 1, 100, int(w.get("limit", 15)))
        width = c9.selectbox("Width", spec_mod.WIDTHS,
                             index=spec_mod.WIDTHS.index(w.get("width", 6)))

        height = st.slider("Height", 160, 700, int(w.get("height", 340)), 20)
        note = st.text_input("Caption (optional)", w.get("note", ""))

        if st.form_submit_button("Apply changes", type="primary"):
            w.update({
                "title": title,
                "type": wtype,
                "x": None if x == "\u2014" else x,
                "y": None if y == "\u2014" else y,
                "agg": agg,
                "color": None if color == "\u2014" else color,
                "grain": None if grain == "none" else grain,
                "sort": None if sort == "none" else sort,
                "limit": int(limit),
                "width": width,
                "height": int(height),
                "note": note,
            })
            st.rerun()


# --------------------------------------------------------- whole dashboard

def render_dashboard(df, spec, edit_mode=False, key_prefix="dash",
                     show_filters=True):
    if not spec.get("widgets"):
        st.markdown(
            "<div class='empty'>This dashboard is empty. "
            "Add a tile, or describe what you want to see in <b>Build with AI</b>.</div>",
            unsafe_allow_html=True,
        )
        return

    # Only one filter bar may own the spec's filter values — a second one
    # rendered elsewhere on the page would overwrite them with its own defaults.
    global_filters = (render_filter_bar(df, spec, key_prefix) if show_filters
                      else spec.get("filters", []))

    index = 0
    for row in spec_mod.pack_rows(spec["widgets"]):
        widths = [w.get("width", 6) for w in row]
        containers = st.columns(widths)
        for container, w in zip(containers, row):
            with container:
                render_one(df, w, global_filters, edit_mode, spec, index,
                           key_prefix)
            index += 1


def add_widget_panel(df, spec, key_prefix="dash"):
    """The 'add a tile' control shown in edit mode."""
    with st.expander("Add a tile", expanded=not spec.get("widgets")):
        c1, c2, c3 = st.columns(3)
        wtype = c1.selectbox("Chart", spec_mod.CHART_TYPES,
                             key=f"{key_prefix}_new_type")
        x = c2.selectbox("Category / X axis", ["—"] + list(df.columns),
                         key=f"{key_prefix}_new_x")
        y = c3.selectbox("Measure / Y axis", ["—"] + list(df.columns),
                         key=f"{key_prefix}_new_y")
        title = st.text_input("Title", key=f"{key_prefix}_new_title",
                              placeholder="What should the reader take away?")
        if st.button("Add tile", type="primary", key=f"{key_prefix}_addtile"):
            spec["widgets"].append(spec_mod.new_widget(
                type=wtype,
                title=title or f"{y if y != '—' else 'Rows'} by {x if x != '—' else ''}".strip(),
                x=None if x == "—" else x,
                y=None if y == "—" else y,
                width=3 if wtype == "kpi" else 6,
                height=150 if wtype == "kpi" else 340,
            ))
            st.rerun()