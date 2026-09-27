# export Specification

## Purpose

The `export` command writes the project's records to `export.json` in an output directory.

## Requirements

### Requirement: Export writes one JSON file
The `export` command SHALL write every record to `<out>/export.json` and exit 0.

#### Scenario: Records are exported
- **GIVEN** a project with three records
- **WHEN** `export --out out` runs
- **THEN** `out/export.json` holds three records and the command exits 0
