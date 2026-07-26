"""
Streamlit renamed `use_container_width=True` to `width="stretch"`. Both are in
the wild depending on the version installed, so pick the right one once here
and spread it as **WIDE at the call sites.
"""

import streamlit as st

try:
    _major, _minor = (int(p) for p in st.__version__.split(".")[:2])
except Exception:
    _major, _minor = 1, 36

if (_major, _minor) >= (1, 49):
    WIDE = {"width": "stretch"}
else:
    WIDE = {"use_container_width": True}