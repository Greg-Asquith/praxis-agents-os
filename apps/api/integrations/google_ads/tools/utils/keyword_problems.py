# apps/api/integrations/google_ads/tools/utils/keyword_problems.py

"""Card problems shared by the tools that add keywords and change them."""

_MATCH_NAMES = {"EXACT": "an exact match", "PHRASE": "a phrase match", "BROAD": "a broad match"}


def keyword_exists(text: str, match_type: str, ad_group: str) -> str:
    return f"“{text}” is already {_MATCH_NAMES[match_type]} keyword in {ad_group}."


def keyword_bid_not_used(campaign: str, strategy: str) -> str:
    return f"{campaign} uses {strategy}, so Google doesn't use a keyword max CPC."
