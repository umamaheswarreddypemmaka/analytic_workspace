"""
Kept from the first version of this app so existing call sites keep working.

New code should call analytics_engine.profile() and ai_builder directly — the
dashboard path doesn't go through here.
"""

import analytics_engine
from executor import ask
from prompts import INSIGHT_SYSTEM


def run(df):
    """Profile a dataframe and return (profile, narrative insight)."""
    result = analytics_engine.profile(df)
    response = ask(analytics_engine.profile_text(result), system=INSIGHT_SYSTEM)
    return result, response