"""
A small synthetic sales-and-collections table.

It exists so the app can be opened and demonstrated on any machine with no
database attached — useful in an interview, and useful for testing chart types
against dates, categories and numbers all at once.
"""

import numpy as np
import pandas as pd


def load_sample(rows=2500, seed=7):
    rng = np.random.default_rng(seed)

    regions = ["Hyderabad", "Chennai", "Bengaluru", "Mumbai", "Pune", "Delhi"]
    segments = ["Retail", "Wholesale", "Government", "Export"]
    products = ["Turmeric", "Chilli", "Rice", "Pulses", "Spice mix", "Oil"]
    reps = ["A. Rao", "S. Iyer", "M. Khan", "P. Nair", "R. Gupta"]

    dates = pd.to_datetime("2024-04-01") + pd.to_timedelta(
        rng.integers(0, 640, rows), unit="D"
    )
    qty = rng.integers(1, 240, rows)
    rate = rng.normal(420, 130, rows).clip(60, 1400).round(2)
    revenue = (qty * rate).round(2)
    cost = (revenue * rng.normal(0.72, 0.09, rows).clip(0.35, 0.96)).round(2)

    df = pd.DataFrame({
        "invoice_date": dates,
        "region": rng.choice(regions, rows, p=[.26, .18, .18, .16, .12, .10]),
        "segment": rng.choice(segments, rows, p=[.45, .3, .15, .10]),
        "product": rng.choice(products, rows),
        "sales_rep": rng.choice(reps, rows),
        "quantity": qty,
        "unit_rate": rate,
        "revenue": revenue,
        "cost": cost,
        "gross_profit": (revenue - cost).round(2),
        "days_to_collect": rng.integers(0, 120, rows),
        "gst_rate": rng.choice([0, 5, 12, 18], rows, p=[.05, .45, .3, .20]),
    })

    # A little realistic mess: some invoices never collected.
    df.loc[df.sample(frac=0.06, random_state=1).index, "days_to_collect"] = np.nan
    return df.sort_values("invoice_date").reset_index(drop=True)