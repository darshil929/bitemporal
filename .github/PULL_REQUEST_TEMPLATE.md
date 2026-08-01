## What changed

## Why

<!-- Cite the phase and task group if plan-driven. -->

## How to test

<!-- Steps someone else can follow. -->

## Checklist

- [ ] `make ci` passes locally, rebased onto current `main`
- [ ] New behaviour has tests; a bug fix has a regression test that fails without the fix
- [ ] Schema change has an Alembic migration; new fact columns carry `as_of_date`
- [ ] New data source registered with tier, curation reference and schema versions
- [ ] Plan or ADR updated if this changed a decision or met an exit criterion
