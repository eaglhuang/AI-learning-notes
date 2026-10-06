# Bilingual newsletter issue contract (pilot)

This isolated pilot validates data offline with Python 3.9+ and only the standard library. It does not generate or publish news, fetch URLs, send mail, change existing article RSS/sitemap, or modify the site homepage.

Run from the repository root:

```sh
python -B -m unittest discover -s tests/newsletter -p 'test_*.py' -v
python -B scripts/newsletter/validate_issue.py newsletter/examples/synthetic-issue.json
```

## Version 1 JSON contract

- `schema_version`: integer `1` (not boolean)
- `date`: real Gregorian calendar date written exactly `YYYY-MM-DD`
- `synthetic`: boolean; `true` marks demonstration/test data, `false` marks editorial issue data
- `items`: exactly 10 objects
  - `id`: unique lowercase ASCII slug, 1–64 characters, letters/digits/hyphens, beginning with a letter or digit
  - `source_url`: absolute HTTPS URL with a DNS hostname and no credentials, whitespace or control characters
  - `zh-TW` and `en`: each an object with nonempty string `title` and `summary`

Unknown fields are tolerated for forward-compatible editorial metadata. Duplicate JSON object keys are rejected. URL duplicates are compared after lowercasing/IDNA-normalizing the hostname, removing the default HTTPS port and fragment, and treating an empty path as `/`. Path/query spelling is preserved; tracking parameters and publisher aliases are not deduplicated. IPv6 literal hosts are outside this pilot contract.

The CLI returns 0 for valid data and 1 for invalid data, unreadable files or malformed JSON, with actionable field paths on stderr. It aggregates structural errors. The Python API `validate_issue(value)` returns a list of errors without modifying input.

## Synthetic example and editorial limits

`examples/synthetic-issue.json` contains invented fixture text and reserved `example.org` URLs. It is not current news and must not be published as a real newsletter. Validation checks completeness and structure, not factual accuracy, translation quality, URL reachability, source credibility or date freshness. Human editorial review remains necessary. The 10-item size is an explicit pilot contract, not a claim that ten publishable stories are always available.
