# bapu-seedred: tests proven by a planted defect

A test earns its place by failing when the behaviour it guards is broken. `bapu-seedred` plants
that defect, one row at a time, and requires the named test to go red.

```
bapu-seedred TABLE [--root DIR] [--only ID ...] [--json]
bapu-seedred TABLE --check [--root DIR]
```

## The table

A JSON file, `{"rows": [...]}` or a bare list. Paths are relative to `--root` (default: the
current directory).

```json
{
  "rows": [
    {
      "id": "cap",
      "file": "retry.py",
      "anchor": "        if delay > cap:",
      "replacement": "        if False:",
      "test": "tests/test_retry.py::test_delays_never_exceed_the_cap",
      "why": "without the cap the delays grow without bound"
    }
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | a unique string or integer; `--only` selects rows by it |
| `file` | the file to mutate, relative to the root and inside it |
| `anchor` | text that must occur exactly once in the file, starting at the beginning of a line |
| `replacement` | what the anchor becomes; it must differ from the anchor |
| `test` | the pytest node id that must fail with the mutation (`path::name`, parametrised ids included) |
| `why` | optional: what would go unnoticed if this test did not exist |

`anchor` and `replacement` may also be lists of lines, joined with newlines; end the list with
`""` to include the final newline. The anchor must start at a line boundary, so include the
line's leading indentation: an anchor written at four spaces would otherwise also match the same
statement indented to eight, and "exactly once" would pass for the wrong line.

## What a run does

Before anything is mutated, every selected row passes static checks: the anchor matches
exactly once, the replacement differs from it, a mutated `.py` file still compiles and reads no
new name that nothing in it defines (a typo would fail the test with a `NameError`, not because
of the defect), the file and the test file exist inside the root, and no id or row appears
twice. Any problem exits 2 and nothing is touched. `--check` stops here, after also asking
pytest to collect each named test.

Then, for each row:

1. **before**: run the named test on the untouched file; it must pass;
2. **after**: write the mutation and run the test again; it must fail;
3. restore the original bytes and timestamps, and verify the bytes;
4. **restored**: run the test once more; it must pass.

Each run is a fresh `python -m pytest <test> -q` process in the root directory. The outcome is
read from pytest's final count line (`1 failed in 0.05s`), never from its exit code: pytest also
exits non-zero for a collection error, and a mutation that merely breaks an import would
otherwise look caught.

| Verdict | Meaning |
|---|---|
| RED | before=passed, after=failed, restored=passed: the test guards the line |
| NOT-RED | the mutation survived, the test already failed before, it fails after the restore, or the mutated run failed with `NameError`, `ImportError`, `SyntaxError` or a relative of them, which says the replacement broke the module rather than the behaviour |
| NO-RESULT | a run printed no count line (a collection error, a crash, a missing test) or timed out |
| SKIPPED | not run because an earlier row gave NO-RESULT (use `--keep-going` to continue) |

Exit codes: 0 when every row is RED, 1 when any row is NOT-RED, 2 for an invalid table, a
NO-RESULT or SKIPPED row, a target file git could not restore (uncommitted, untracked or
ignored), or a failed restore.

A NOT-RED row is a finding about the test, not about the code: the test does not guard the
line its row names. Suspect the test before the code.

## Safety

The runner edits files in place, so it is careful to put them back:

- the original bytes are held in memory and written back in a `finally` block, including on
  Ctrl-C, SIGTERM and SIGHUP; a signal that arrives during the restore itself is held until the
  file is back; the restored bytes are read back and compared, and on any mismatch the original
  is saved to a temporary file whose path the error names (exit 2);
- the original timestamps are restored too; while mutated, the file gets a modification time at
  least one second away from the original, and the module's cached bytecode is removed, so no
  bytecode compiled from one version can stand in for the other;
- test runs set `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`, so they leave no caches;
- inside a git work tree, the runner refuses to start when git could not restore a target
  file: uncommitted, untracked or ignored (`--allow-dirty` overrides), so `git checkout` remains a
  way back if the process is killed outright; a git error other than "not a git repository" stops
  the run instead of skipping the check.

Run it only on code you trust: it executes the project's tests.

## Choosing mutations

A good row removes exactly the behaviour its test claims to guard:

- delete or disable the guard: `if percent > 50:` becomes `if False:`;
- put the defect back: revert the fix the test was written for;
- invert or loosen a boundary: `<=` becomes `<`.

A replacement that is a no-op in disguise (a changed comment, a body swapped for an equivalent
one) will stay green and tell you nothing. If a row stays green, first check that the mutation
really removes the behaviour; then fix the test.

## This repository

This repository proves its own tests the same way. [`seedred.json`](../seedred.json) holds one
row per guard in `src/bapu/`, and continuous integration runs it:

```
bapu-seedred seedred.json
```

## Limits

- Tests are run with pytest; the mutated file can be any text file.
- One row mutates one place in one file.
- The runner does not check that the named test executes the mutated line; a RED row shows
  that the test is sensitive to the change, which is the claim the row makes.
- The exception a mutated run failed with is read from pytest's short summary line (the runner
  widens pytest's terminal so the line is not cut). A project that turns that summary off
  (`-r` in its pytest options) loses the broken-module check, and each row's `failure` is empty.
- Other exceptions (a `TypeError` from a replacement, say) count as the test failing; make each
  replacement the smallest change that removes the behaviour.
