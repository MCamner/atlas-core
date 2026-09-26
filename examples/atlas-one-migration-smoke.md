# Atlas One Migration Smoke

This fixture-backed smoke demonstrates an opt-in migration preview without
assuming an external Atlas One export format. The source fixture is
[`legacy-prompt.md`](../tests/fixtures/atlas_one_migration/legacy-prompt.md);
the assertions are in
[`test_atlas_one_migration_smoke.py`](../tests/test_atlas_one_migration_smoke.py).

Run it with:

```sh
python -m unittest discover -s tests -p 'test_atlas_one_migration_smoke.py' -v
```

The test copies the selected fixture into a temporary archive, records its
SHA-256 (`4e96d663d071da055d6fcffa3711a76e17e4eaf981b0585ed9cecfe833da9e08`),
and produces a preview with the explicit task
`granska repot efter hårdkodade lösenord`. It leaves the legacy `Action:` line
unmapped and checks that the archived and original bytes retain the original
digest. The preview records `run_requested: false` and an empty
`write_capabilities` list. It invokes neither `atlas run` nor a write adapter;
the operator must separately review and start the task.

Observed on 2026-09-26:

```text
Ran 1 test
OK
```

This is evidence for the manual preview/handoff path only. It does not claim
that Atlas Core imports, validates or executes Atlas One's external format.
