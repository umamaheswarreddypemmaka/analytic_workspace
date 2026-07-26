"""
Natural language -> dashboard spec.

Two calls: build a dashboard from a sentence, or edit the one on screen from a
sentence. Both go through spec.validate_dashboard() before anything renders, so
a hallucinated column name becomes a visible warning instead of a stack trace.
"""

import json

import pandas as pd

import prompts
import spec as spec_mod
from executor import ask


def schema_digest(df, max_uniques=8):
    """A compact, model-readable description of the dataframe."""
    lines = []
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            kind = "numeric"
            detail = f"min={_fmt(s.min())}, max={_fmt(s.max())}, mean={_fmt(s.mean())}"
        elif pd.api.types.is_datetime64_any_dtype(s):
            kind = "date"
            detail = f"from {s.min()} to {s.max()}"
        else:
            kind = "text"
            vals = s.dropna().astype(str).unique()[:max_uniques]
            detail = f"{s.nunique()} distinct; e.g. " + ", ".join(vals)
        lines.append(f"- {col} ({kind}): {detail}")
    return f"{len(df)} rows, {len(df.columns)} columns\n" + "\n".join(lines)


def _fmt(v):
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def sample_text(df, n=5):
    return df.head(n).to_csv(index=False)


def extract_json(text):
    """Pull the JSON object out of a reply that may be wrapped in fences or prose."""
    if not text:
        raise ValueError("The model returned an empty reply.")
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in the model's reply.")
    return json.loads(t[start:end + 1])


def generate_dashboard(request, df, dataset_name=None, model=None):
    """Returns (validated_spec, problems)."""
    raw = ask(
        prompts.builder_prompt(request, schema_digest(df), sample_text(df)),
        system=prompts.BUILDER_SYSTEM,
        json_mode=True,
        model=model,
    )
    draft = extract_json(raw)
    validated, problems = spec_mod.validate_dashboard(draft, df)
    validated["dataset"] = dataset_name
    for w in validated["widgets"]:
        w["id"] = spec_mod.new_id()
    return validated, problems


def edit_dashboard(request, current_spec, df, model=None):
    """Apply a plain-English change to an existing dashboard."""
    raw = ask(
        prompts.editor_prompt(request, json.dumps(current_spec, indent=1),
                              schema_digest(df)),
        system=prompts.EDITOR_SYSTEM,
        json_mode=True,
        model=model,
    )
    draft = extract_json(raw)
    validated, problems = spec_mod.validate_dashboard(draft, df)
    validated["dataset"] = current_spec.get("dataset")
    validated["name"] = current_spec.get("name") or validated["name"]
    for w in validated["widgets"]:
        if not w.get("id"):
            w["id"] = spec_mod.new_id()
    return validated, problems


MEASURE_HINTS = ("amount", "revenue", "sales", "value", "total", "profit",
                 "margin", "net", "gross", "balance", "turnover", "cost",
                 "expense", "tax", "qty", "quantity")
IGNORE_HINTS = ("id", "code", "no", "number", "pin", "year", "rate", "pct",
                "percent", "flag")


def text_columns(df, max_distinct=40):
    """Low-cardinality text-ish columns — the ones worth grouping by."""
    out = []
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        if 1 < s.nunique(dropna=True) <= max_distinct:
            out.append(c)
    return out


def measure_columns(df):
    """Numeric columns ranked as likely business measures, IDs pushed to the back."""
    numeric = list(df.select_dtypes(include="number").columns)

    def score(c):
        low = c.lower()
        s = 0
        hit = next((i for i, h in enumerate(MEASURE_HINTS) if h in low), None)
        if hit is not None:
            s -= (len(MEASURE_HINTS) - hit)                # named like a measure
        elif (pd.api.types.is_integer_dtype(df[c])
              and df[c].nunique(dropna=True) == len(df)):
            s += 20                                       # looks like a row key
        if any(low == h or low.endswith("_" + h) for h in IGNORE_HINTS):
            s += 10                                       # rate / pct / id suffix
        return s

    return sorted(numeric, key=score)


def starter_dashboard(df, name="Overview"):
    """
    A sensible dashboard with no LLM call at all.

    This is the fallback when no API key is configured, and it's also what a
    new person sees before they type anything — an empty screen is a dead end.
    """
    numeric = measure_columns(df)
    dates = list(df.select_dtypes(include=["datetime", "datetimetz"]).columns)
    cats = text_columns(df)

    d = spec_mod.new_dashboard(name)
    d["description"] = "Auto-built from the shape of the data. Edit anything."

    d["widgets"].append(spec_mod.new_widget(
        type="kpi", title="Rows", agg="count", width=3, height=150))
    for m in numeric[:3]:
        d["widgets"].append(spec_mod.new_widget(
            type="kpi", title=f"Total {m}", y=m, agg="sum", width=3, height=150))

    if dates and numeric:
        d["widgets"].append(spec_mod.new_widget(
            type="line", title=f"{numeric[0]} over time", x=dates[0], y=numeric[0],
            agg="sum", grain="month", sort=None, limit=100, width=12))

    if cats and numeric:
        d["widgets"].append(spec_mod.new_widget(
            type="bar", title=f"{numeric[0]} by {cats[0]}", x=cats[0], y=numeric[0],
            agg="sum", width=6))
    if len(cats) > 1:
        d["widgets"].append(spec_mod.new_widget(
            type="donut", title=f"Share by {cats[1]}", x=cats[1],
            y=numeric[0] if numeric else None,
            agg="sum" if numeric else "count", width=6))
    if len(numeric) > 1:
        d["widgets"].append(spec_mod.new_widget(
            type="scatter", title=f"{numeric[0]} vs {numeric[1]}",
            x=numeric[0], y=numeric[1], width=6))
        d["widgets"].append(spec_mod.new_widget(
            type="heatmap", title="How the numbers move together", width=6))

    validated, _ = spec_mod.validate_dashboard(d, df)
    return validated