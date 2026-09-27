## ADDED Requirements

### Requirement: Export refuses to replace an existing file
The `export` command SHALL exit 3 with the message `output exists` when `<out>/export.json`
already exists and `--force` is not given.

#### Scenario: A second export without --force is refused
- **GIVEN** `out/export.json` was written by an earlier run
- **WHEN** `export --out out` runs again without `--force`
- **THEN** the command exits 3 and prints `output exists`
- **AND** `out/export.json` is byte-identical to the earlier file

### Requirement: Force replaces the existing file
The `export` command SHALL replace `<out>/export.json` and exit 0 when `--force` is given.

#### Scenario: A second export with --force replaces the file
- **GIVEN** `out/export.json` was written by an earlier run
- **WHEN** a record is added and `export --out out --force` runs
- **THEN** the command exits 0 and `out/export.json` holds the added record
