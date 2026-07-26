"""
Dataset profiling.

The earlier version of this module wrote PNGs to an output folder and the app
displayed whatever files it found there. That meant charts from one dataset
leaked into the next run and nothing was interactive. Profiling now returns
data; charts.py owns drawing.
"""

import pandas as pd


def profile(df):
    """Structured profile used by the Explore tab and by the AI narrative."""
    missing = df.isnull().sum()
    missing_pct = (missing / max(len(df), 1) * 100).round(1)

    quality = []
    dupes = int(df.duplicated().sum())
    if dupes:
        quality.append(f"{dupes:,} duplicate rows ({dupes/len(df)*100:.1f}% of the table).")
    for col in df.columns:
        if df[col].nunique(dropna=True) <= 1:
            quality.append(f"'{col}' holds a single value — nothing to analyse there.")
        if missing_pct.get(col, 0) > 30:
            quality.append(f"'{col}' is {missing_pct[col]}% empty.")

    return {
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "column_types": df.dtypes.astype(str).to_dict(),
        "missing": pd.DataFrame({
            "Column": missing.index,
            "Missing": missing.values,
            "Missing %": missing_pct.values,
        }).query("Missing > 0").reset_index(drop=True),
        "numeric_summary": (df.describe().T.round(2).reset_index()
                            .rename(columns={"index": "Column"})
                            if not df.select_dtypes(include="number").empty
                            else pd.DataFrame()),
        "categorical_summary": _categorical_summary(df),
        "quality_flags": quality,
    }


def _categorical_summary(df):
    rows = []
    text_cols = [c for c in df.columns
                 if not pd.api.types.is_numeric_dtype(df[c])
                 and not pd.api.types.is_datetime64_any_dtype(df[c])]
    for col in text_cols:
        s = df[col]
        top = s.mode(dropna=True)
        rows.append({
            "Column": col,
            "Distinct": int(s.nunique(dropna=True)),
            "Most common": str(top.iloc[0]) if len(top) else "—",
            "Its share %": round(float(s.eq(top.iloc[0]).mean() * 100), 1) if len(top) else 0.0,
        })
    return pd.DataFrame(rows)


def profile_text(p):
    """Flatten a profile into something compact enough to hand an LLM."""
    parts = [f"{p['rows']:,} rows x {p['columns']} columns",
             "Column types: " + ", ".join(f"{k} ({v})" for k, v in p["column_types"].items())]
    if not p["missing"].empty:
        parts.append("Missing values:\n" + p["missing"].to_string(index=False))
    if not p["numeric_summary"].empty:
        parts.append("Numeric summary:\n" + p["numeric_summary"].to_string(index=False))
    if not p["categorical_summary"].empty:
        parts.append("Category summary:\n" + p["categorical_summary"].to_string(index=False))
    if p["quality_flags"]:
        parts.append("Quality flags: " + " ".join(p["quality_flags"]))
    return "\n\n".join(parts)


# Old name, kept so nothing that imported it breaks.
def analyze_data(df):
    return profile(df)