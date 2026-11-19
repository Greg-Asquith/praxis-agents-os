<!-- apps/api/tests/fixtures/mail_merge_evals/README.md -->

# Mail merge eval fixtures

The `mail_merge_*` cases in `evals/datasets/agent_behavior.yaml` use these:

- `contacts.csv`: 40 synthetic people with clear full names, addresses, and
  business names. The `ExpectedMerge` evaluator reads the expected
  addresses, first names, and companies from it.
- `contacts_ambiguous.csv`: 10 synthetic supplier contacts. Four have no
  clear first name ("Dr Patel", "J. Okafor", "Accounts Team", "Mrs Hughes").
- `read_table_contacts.json` and `read_table_contacts_ambiguous.json`: the
  `read_table` results for those files, built with the document worker's
  `read_delimited_table` and the tool's `file_result`, so the values are
  untrusted nodes as in production.

Every address uses an `example.com`, `example.org`, or `example.net`
domain. Rebuild the JSON files when the `read_table` result changes.
