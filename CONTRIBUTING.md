# Contributing

Thanks for helping. A few things keep this project trustworthy.

## Run it

```bash
pip install -e ".[dev]"
pytest -q                      # about two minutes; the UI tests use Chrome if it is installed
```

## Layout

```
src/proxy2model/
├── ingest/   exports, browser recording and crawls: parse, mask, infer value types
├── core/     the model: build, graph reasoning, context for AI, diffs
├── db/       graph.db and the BQL query language
├── report/   the HTML report, animation, screenshots
├── export/   OpenAPI
├── recon/    opt-in external recon
├── cli/      one module per group of commands; ui.py for terminal output
└── data/     bundled data (public suffix list, fonts)
```

## Ground rules

- **Redaction first.** Any new way of reading input must mask values before anything is stored. Add the new shape to `tests/test_redaction_realistic.py`; the test fails if the value survives.
- **Evidence for every claim.** A new node, edge or answer must cite the request behind it.
- **Never call anything a vulnerability.** This is a model builder, not a scanner. Leads are hypotheses to verify.
- **Deterministic.** The same input gives the same output. No timestamps or random ids in model files (see `SOURCE_DATE_EPOCH`).
- **No new runtime dependencies** in the Python package.
- **Docs stay short and public.** Say what it does and how to use it; no internal notes.

## Releasing

1. Set `__version__` in `src/proxy2model/__init__.py` and give it a `## X.Y.Z` section in `CHANGELOG.md`.
2. Rebuild the demo and example reports (`./demo.sh`, the Juice Shop loop in `docs/examples/README.md`).
3. Look at it, not only the tests: open the report and the landing page, run `proxy2model` and a build,
   and record a few pages with `browse`. Unit tests do not see a stale logo or a broken flow.
4. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`. The release workflow checks the tag
   against the version and changelog, runs the tests, publishes to PyPI and creates the GitHub release.

## Pull requests

Describe what changed and why, and say how you tested it. Do not attach real captures: use the samples in `samples/` or invent one. Keep a PR to one change.
