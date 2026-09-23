# Tests

Run the offline unit and workflow suite from the project root:

```powershell
python -m unittest discover -s tests -v
```

The current suite uses local catalogs and isolated SQLite files. It does not call an LLM, supplier, marketplace or payment service. Coverage includes procurement/approval, exact catalog matches, SQLite migrations through schema v5, Firebird contractor matching, partial delivery, finance, full-database analytics, local price history, and B2C shopping workflows. SDK construction is checked without a live model call.
