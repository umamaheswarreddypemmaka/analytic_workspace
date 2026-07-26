# AI Analytics Workspace

A self-service BI tool: connect to data, then build dashboards either by hand or
by describing what you want. Dashboards are saved per person, so two people
looking at the same database keep their own views.

## What it does

**Per-person dashboards.** Sign in, build a dashboard, save it. It belongs to
your account. Tick *Share with the team* and it also appears for everyone else,
read-only in practice — they can open it, tweak it, and save their own copy.

**Quick changes.** Turn on *Edit mode* and every tile gains move / resize /
duplicate / remove controls plus an inline editor: swap the chart type, change
the measure, group by something else, roll dates up to month or quarter, sort,
limit to the top N. No re-running anything.

**Dashboards from a prompt.** Type "monthly revenue and gross profit, split by
region, and flag the segments where margin is falling" and get a working
dashboard. Then keep talking to it: "drop the pie chart and add days-to-collect
by customer segment" edits what's on screen.

**Global slicers.** Filters set at the top of a dashboard apply to every tile —
the cross-filtering behaviour people expect from Power BI.

**Explore tab.** Row counts, missing values, data-quality flags, category and
numeric summaries, and an optional written summary from the model.

## How the prompt-to-dashboard part works

The model never renders anything and never sees a database connection. It writes
JSON:

```json
{"name": "Sales overview",
 "widgets": [{"type": "bar", "title": "Revenue by region",
              "x": "region", "y": "revenue", "agg": "sum", "width": 6}]}
```

The pipeline is:

1. `ai_builder.schema_digest()` sends real column names, types and ranges — so
   the model works from the actual schema rather than guessing.
2. The model returns a spec.
3. `spec.validate_dashboard()` checks every field against the dataframe.
   Unknown columns are dropped, unknown chart types fall back to a bar, out-of-
   range values are clamped, and each repair is reported to the user.
4. `charts.render_widget()` draws it.

The same JSON shape is what the manual editor writes, which is the point: a
prompted dashboard and a hand-built one are the same object, so anything the AI
makes stays editable, savable and exportable.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # add your OpenRouter key
streamlit run app.py
```

Click **Load sample data** in the sidebar and then **Auto-build** to see it
working without a database or an API key.

For SQL Server you also need an ODBC driver on the machine ("ODBC Driver 17 for
SQL Server" or 18). Windows usually has one; on macOS/Linux install
`msodbcsql18`. If `sqlalchemy` and `pyodbc` aren't installed, the app still runs
on files and sample data — the SQL Server option just doesn't appear.

The first account you create is the admin account. Accounts and dashboards live
in `app_data.db` (SQLite), so nothing else needs to be running.

## Files

| File | Job |
|---|---|
| `app.py` | Streamlit shell: sign-in, data sources, the three tabs |
| `spec.py` | The dashboard/widget JSON contract, validation, grid layout |
| `charts.py` | Spec + dataframe → Plotly figure. Filter → aggregate → draw |
| `dashboard_ui.py` | Renders the canvas and the inline editor |
| `ai_builder.py` | Schema digest, prompt → spec, spec + prompt → spec |
| `executor.py` | OpenRouter client. Key comes from the environment |
| `prompts.py` | System prompts, including the JSON contract |
| `analytics_engine.py` | Dataset profiling and quality flags |
| `db_connector.py` | SQL Server engine, read-only query guard |
| `store.py` | SQLite: users, saved datasets, saved dashboards |
| `sample_data.py` | Synthetic sales table so the app demos anywhere |
| `compat.py` | Handles the Streamlit `use_container_width` → `width` rename |

## What changed from the first version

- Charts were matplotlib PNGs written to an `output/` folder and displayed by
  listing that folder. Files from one dataset leaked into the next run and
  nothing was interactive. Charts are now Plotly figures rendered from a spec —
  hover, zoom, legend toggles, and no files on disk.
- The AI wrote prose about the data. It now writes the dashboard itself, and the
  prose summary is one optional button on the Explore tab.
- There was one implicit dashboard, the same for everyone. Dashboards are now
  objects owned by an account, saved, reopened, shared and exported.
- The query box accepted any SQL. `db_connector.run_query()` now rejects
  anything that isn't a single SELECT, and table names are bracket-quoted. Point
  the app at a read-only login as well.
- The OpenRouter key was hardcoded in `executor.py`. It now comes from the
  environment only, and `.env` is gitignored.

## Worth knowing before you demo it

- Authentication is PBKDF2 over SQLite — fine for an internal tool behind a VPN,
  not a substitute for SSO.
- Data is loaded into memory per session, so cap large tables with the row limit
  or a `TOP` clause. Beyond a few hundred thousand rows, push the aggregation
  into SQL instead.
- Streamlit has no native drag-and-drop. Tiles are moved with buttons on a
  12-column grid. Swapping `spec.pack_rows()` for `streamlit-elements` would give
  true drag-and-drop without changing the spec.