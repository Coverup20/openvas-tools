# reports/

Report export, transformation and generation pipeline.

## Structure

| Path | Description |
|---|---|
| `export/` | Raw XML exports from gvmd via GMP (gitignored — sensitive) |
| `transform/` | Python/lxml transformation scripts |
| `templates/` | ODT templates for report generation |

## Pipeline

```
Greenbone scan
  → report UUID
  → GMP export (gvm-cli / python-gvm)
  → raw XML
  → XML transformation
  → ODT template rendering
  → final reports
```

## Data safety

- All export files contain vulnerability evidence and must be handled as sensitive.
- XML files in `export/` are gitignored by default.
- ODT template files in `templates/` are gitignored (contain design layouts).
- Processed reports must be stored outside the repository.
