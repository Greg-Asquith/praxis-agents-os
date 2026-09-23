# apps/api/services/integrations/report_results.py

"""Shared retrieval guidance for structured integration reports."""

REPORT_RESULT_GUIDANCE = (
    " Oversized direct results arrive as an incomplete preview with the provider result in "
    "`data`, per-list counts in `lists`, and a `file_reference` to the complete returned JSON. "
    "Provider row limits still apply. Never calculate whole-report totals from a preview. "
    "If run_code is available and permitted, pass file_ids=[file_reference] to aggregate or "
    "filter the saved data instead of repeatedly paging raw rows with read_file. Configured "
    "OpenAI and Anthropic helpers mount the complete File within their input limits; Google "
    "accepts only bounded text inputs. Use read_file with file_id=file_reference for bounded "
    "inspection, or narrow the query when a suitable helper is unavailable."
)
