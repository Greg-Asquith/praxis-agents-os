# Document eval fixtures

The `document_*` cases in `evals/datasets/agent_behavior.yaml` place these
tool results in model history. Each read fixture is the worker's `read` output
for a small file built with `python-pptx`, `openpyxl`, or `python-docx`,
headed by the File and revision ids the read tools add:

- `read_presentation_template.json`: the bundled default deck with one title
  slide.
- `read_workbook_regional_sales.json`: a Sales sheet of six regions by
  quarter, with no totals.
- `read_word_document_supplier_agreement.json`: a short agreement with a
  delivery date paragraph.

`google_ads_report_preview.json` is the preview envelope for a saved
2,400-row search term report, built with `preview_structured_result`.

Rebuild them when the read or preview contract changes, so the evals show
models what production returns.
