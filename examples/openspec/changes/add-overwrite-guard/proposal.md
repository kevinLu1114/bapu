## Why

Running `export` twice replaces the first result without a word.

## What Changes

- `export` refuses to replace an existing `export.json` unless `--force` is given.

## Impact

- Affected specs: `export`
