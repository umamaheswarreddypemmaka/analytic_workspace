"""
AI Analytics Workspace — per-person dashboards you can build by hand or by asking.

Run:  streamlit run app.py
"""

import json
import os

import pandas as pd
import streamlit as st

import ai_builder
import analytics_engine
import dashboard_ui
import db_connector as dbc
import spec as spec_mod
import store
from compat import WIDE
import executor
from executor import LLMNotConfigured, ask
from prompts import INSIGHT_SYSTEM
from sample_data import load_sample

st.set_page_config(page_title="AI Analytics Workspace", layout="wide",
                   initial_sidebar_state="expanded")
dashboard_ui.inject_css()
store.init_db()


# ------------------------------------------------------------- sign in

def sign_in():
    st.markdown("## AI Analytics Workspace")
    st.caption("Sign in — dashboards are saved against your account.")

    first_run = store.user_count() == 0
    tabs = st.tabs(["Sign in", "Create account"] if not first_run else ["Create the first account"])

    if not first_run:
        with tabs[0]:
            u = st.text_input("Username", key="li_u")
            p = st.text_input("Password", type="password", key="li_p")
            if st.button("Sign in", type="primary"):
                user = store.verify_user(u, p)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("That username and password don't match. Try again.")

    with tabs[-1]:
        u = st.text_input("Choose a username", key="su_u")
        n = st.text_input("Display name", key="su_n")
        p = st.text_input("Choose a password", type="password", key="su_p")
        if st.button("Create account"):
            try:
                store.create_user(u, p, n, role="admin" if first_run else "analyst")
                st.session_state.user = store.verify_user(u, p)
                st.rerun()
            except Exception as e:
                st.error(f"Could not create the account: {e}")


if "user" not in st.session_state:
    sign_in()
    st.stop()

user = st.session_state.user
me = user["username"]


# --------------------------------------------------------- sidebar: data

st.sidebar.markdown(f"**{user.get('display_name') or me}**")
if st.sidebar.button("Sign out"):
    for k in ("user", "df", "dataset_name", "spec", "spec_source"):
        st.session_state.pop(k, None)
    st.rerun()

st.sidebar.divider()
st.sidebar.subheader("Data")

sources = ["Sample data", "Upload a file"]
if dbc.SQLALCHEMY_AVAILABLE:
    sources.append("SQL Server")
source = st.sidebar.radio("Source", sources, label_visibility="collapsed")
if not dbc.SQLALCHEMY_AVAILABLE:
    st.sidebar.caption("SQL Server needs sqlalchemy and pyodbc installed.")

if source == "Sample data":
    if st.sidebar.button("Load sample data", **WIDE):
        st.session_state.df = load_sample()
        st.session_state.dataset_name = "sample_sales"
        st.rerun()

elif source == "Upload a file":
    up = st.sidebar.file_uploader("CSV or Excel", type=["csv", "xlsx", "xls"])
    if up is not None and st.sidebar.button("Load file", **WIDE):
        df = (pd.read_csv(up) if up.name.lower().endswith(".csv")
              else pd.read_excel(up))
        st.session_state.df = df
        st.session_state.dataset_name = os.path.splitext(up.name)[0]
        st.rerun()

else:
    server = st.sidebar.text_input("Server", placeholder="localhost\\SQLEXPRESS")
    database = st.sidebar.text_input("Database")
    driver = st.sidebar.selectbox("ODBC driver", dbc.DRIVERS)
    auth = st.sidebar.radio("Authentication",
                            ["SQL Server Authentication", "Windows Authentication"])
    username = password = None
    trusted = auth.startswith("Windows")
    if not trusted:
        username = st.sidebar.text_input("Username")
        password = st.sidebar.text_input("Password", type="password")

    if st.sidebar.button("Connect", **WIDE):
        try:
            engine = dbc.get_sqlserver_engine(server, database, username, password,
                                              trusted, driver)
            dbc.test_connection(engine)
            st.session_state.engine = engine
            st.sidebar.success("Connected.")
        except Exception as e:
            st.session_state.pop("engine", None)
            st.sidebar.error(f"Connection failed: {e}")

    if st.session_state.get("engine"):
        mode = st.sidebar.radio("Pick data", ["Table", "SQL query"])
        if mode == "Table":
            try:
                tables = dbc.list_tables(st.session_state.engine)
                options = [f"{r.TABLE_SCHEMA}.{r.TABLE_NAME}" for r in tables.itertuples()]
                pick = st.sidebar.selectbox("Table", options)
                cap = st.sidebar.number_input("Row limit", 100, 100_000, 5000, 100)
                if st.sidebar.button("Load table", **WIDE):
                    schema, table = pick.split(".", 1)
                    st.session_state.df = dbc.preview_table(
                        st.session_state.engine, schema, table, int(cap))
                    st.session_state.dataset_name = pick
                    st.rerun()
            except Exception as e:
                st.sidebar.error(f"Could not list tables: {e}")
        else:
            sql = st.sidebar.text_area("SELECT statement",
                                       "SELECT TOP 1000 * FROM dbo.your_table")
            if st.sidebar.button("Run query", **WIDE):
                try:
                    st.session_state.df = dbc.run_query(st.session_state.engine, sql)
                    st.session_state.dataset_name = "custom_query"
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(str(e))

st.sidebar.divider()
with st.sidebar.expander("AI settings", expanded=not executor.is_configured()):
    st.caption(f"OpenRouter key: {executor.key_source()}")
    typed = st.text_input("Paste a key", type="password",
                          placeholder="sk-or-v1-...",
                          help="Used for this session only — nothing is written to disk.")
    if st.button("Use this key", **WIDE):
        executor.set_api_key(typed)
        st.session_state.runtime_key = typed
        st.rerun()

# A key typed into the sidebar has to be re-applied after each rerun, because
# Streamlit re-imports nothing but does reset module-level state on restart.
if st.session_state.get("runtime_key") and not executor.is_configured():
    executor.set_api_key(st.session_state.runtime_key)

if "df" in st.session_state:
    df = st.session_state.df
    st.sidebar.caption(
        f"{st.session_state.get('dataset_name','dataset')} — "
        f"{df.shape[0]:,} rows x {df.shape[1]} columns"
    )


# --------------------------------------------------------------- helpers

def require_data():
    if "df" not in st.session_state:
        st.info("Pick a data source in the sidebar to get started. "
                "**Load sample data** is the fastest way in.")
        st.stop()
    return st.session_state.df


def current_spec(df):
    if "spec" not in st.session_state:
        st.session_state.spec = spec_mod.new_dashboard(
            "My dashboard", st.session_state.get("dataset_name"))
    return st.session_state.spec


# ----------------------------------------------------------------- pages

tab_dash, tab_ai, tab_explore = st.tabs(
    ["Dashboards", "Build with AI", "Explore the data"]
)

# ---- Dashboards ---------------------------------------------------------
with tab_dash:
    df = require_data()
    spec = current_spec(df)

    saved = store.list_dashboards(me)
    names = [f"{d['name']}" + ("" if d["owner"] == me else f"  (shared by {d['owner']})")
             for d in saved]

    top = st.columns([3, 2, 2, 2, 2])
    with top[0]:
        pick = st.selectbox("Open a dashboard", ["—"] + names, key="open_pick")
        if pick != "—" and st.button("Open", **WIDE):
            chosen = saved[names.index(pick)]
            validated, problems = spec_mod.validate_dashboard(chosen["spec"], df)
            st.session_state.spec = validated
            if problems:
                st.warning("Some tiles didn't match this dataset:\n\n- " +
                           "\n- ".join(problems[:6]))
            st.rerun()

    with top[1]:
        st.write("")
        if st.button("New blank", **WIDE):
            st.session_state.spec = spec_mod.new_dashboard(
                "My dashboard", st.session_state.get("dataset_name"))
            st.rerun()
    with top[2]:
        st.write("")
        if st.button("Auto-build", **WIDE,
                     help="Build a starter dashboard from the shape of the data — no AI call."):
            st.session_state.spec = ai_builder.starter_dashboard(
                df, name=f"{st.session_state.get('dataset_name','Data')} overview")
            st.rerun()
    with top[3]:
        st.write("")
        edit_mode = st.toggle("Edit mode", key="edit_mode")
    with top[4]:
        st.write("")
        st.download_button("Export JSON", json.dumps(spec, indent=2),
                           file_name=f"{spec['name'].replace(' ','_')}.json",
                           mime="application/json", **WIDE)

    st.markdown(f"### {spec.get('name','Untitled')}")
    if spec.get("description"):
        st.caption(spec["description"])

    if edit_mode:
        e1, e2, e3 = st.columns([4, 2, 2])
        spec["name"] = e1.text_input("Dashboard name", spec.get("name", ""))
        shared = e2.checkbox("Share with the team",
                             value=any(d["name"] == spec["name"] and d["owner"] == me
                                       and d["shared"] for d in saved))
        e3.write("")
        if e3.button("Save dashboard", type="primary", **WIDE):
            store.save_dashboard(me, spec["name"], spec, shared)
            st.success(f"Saved “{spec['name']}”.")
        dashboard_ui.add_widget_panel(df, spec, "dash")

    dashboard_ui.render_dashboard(df, spec, edit_mode=edit_mode,
                                  key_prefix="dash")

    if edit_mode:
        with st.expander("Delete a dashboard"):
            mine = [d["name"] for d in saved if d["owner"] == me]
            if mine:
                target = st.selectbox("Which one", mine, key="del_pick")
                if st.button("Delete permanently"):
                    store.delete_dashboard(me, target)
                    st.rerun()
            else:
                st.caption("You haven't saved a dashboard yet.")

# ---- Build with AI ------------------------------------------------------
with tab_ai:
    df = require_data()
    spec = current_spec(df)

    st.markdown("### Describe the dashboard you want")
    st.caption("Ask in plain English. The result is a normal dashboard — "
               "every tile stays editable afterwards.")

    examples = [
        "Monthly revenue and gross profit trend, with region and segment breakdowns",
        "Collections dashboard: who pays late, by customer segment and rep",
        "Top 10 products by margin, plus a KPI row for revenue, cost and profit",
    ]
    cols = st.columns(len(examples))
    for i, ex in enumerate(examples):
        if cols[i].button(ex, key=f"ex_{i}", **WIDE):
            st.session_state.ai_request = ex

    request = st.text_area("Your request", key="ai_request", height=90,
                           placeholder="e.g. Show revenue by region each month, "
                                       "and flag segments where profit is falling")

    mcol1, mcol2 = st.columns([2, 3])
    choices = executor.KNOWN_MODELS + ["Other (type it in)"]
    default = os.getenv("OPENROUTER_MODEL", executor.DEFAULT_MODEL)
    picked = mcol1.selectbox(
        "Model", choices,
        index=choices.index(default) if default in choices else 1,
        help="Model ids get retired periodically. If one stops working, pick another.")
    if picked == "Other (type it in)":
        model = mcol2.text_input("Model id", default,
                                 placeholder="provider/model-name")
    else:
        model = picked
        mcol2.caption("")

    b1, b2 = st.columns(2)
    if b1.button("Build dashboard", type="primary", **WIDE):
        if not request.strip():
            st.warning("Type what you want to see first.")
        else:
            with st.spinner("Designing the dashboard…"):
                try:
                    new_spec, problems = ai_builder.generate_dashboard(
                        request, df, st.session_state.get("dataset_name"), model)
                    st.session_state.spec = new_spec
                    if problems:
                        st.warning("Adjusted a few things:\n\n- " +
                                   "\n- ".join(problems[:6]))
                    st.success("Built. Open the Dashboards tab to edit or save it.")
                except LLMNotConfigured as e:
                    st.error(str(e))
                    st.info("No key? **Auto-build** on the Dashboards tab makes a "
                            "starter dashboard with no AI call.")
                except Exception as e:
                    st.error(f"Could not build that: {e}")

    if b2.button("Change the current dashboard", **WIDE):
        if not request.strip():
            st.warning("Describe the change first, e.g. 'drop the pie chart and "
                       "add profit margin by month'.")
        else:
            with st.spinner("Applying the change…"):
                try:
                    new_spec, problems = ai_builder.edit_dashboard(
                        request, spec, df, model)
                    st.session_state.spec = new_spec
                    if problems:
                        st.warning("Adjusted a few things:\n\n- " +
                                   "\n- ".join(problems[:6]))
                    st.success("Updated.")
                except LLMNotConfigured as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Could not apply that change: {e}")

    if spec.get("widgets"):
        st.divider()
        st.caption("Preview")
        dashboard_ui.render_dashboard(df, spec, edit_mode=False,
                                      key_prefix="preview", show_filters=False)

# ---- Explore ------------------------------------------------------------
with tab_explore:
    df = require_data()
    st.markdown("### What's in this data")
    st.dataframe(df.head(50), **WIDE, height=280)

    p = analytics_engine.profile(df)
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows", f"{p['rows']:,}")
    c2.metric("Columns", p["columns"])
    c3.metric("Columns with gaps", len(p["missing"]))

    if p["quality_flags"]:
        st.warning("Worth fixing before you trust the numbers:\n\n- " +
                   "\n- ".join(p["quality_flags"][:8]))

    left, right = st.columns(2)
    with left:
        st.markdown("**Missing values**")
        st.dataframe(p["missing"], **WIDE, hide_index=True)
    with right:
        st.markdown("**Categories**")
        st.dataframe(p["categorical_summary"], **WIDE,
                     hide_index=True)

    st.markdown("**Numeric summary**")
    st.dataframe(p["numeric_summary"], **WIDE, hide_index=True)

    if st.button("Write the insight summary", type="primary"):
        with st.spinner("Reading the profile…"):
            try:
                st.markdown(ask(analytics_engine.profile_text(p),
                                system=INSIGHT_SYSTEM))
            except LLMNotConfigured as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Could not generate insights: {e}")