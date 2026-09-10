# test_cases

This directory is reserved for generated OpenFOAM validation cases. It is not a
unit-test suite and is not read by the production BO workflow.

The mesh-validation command may recreate `structured_mesh_sweep/` here:

```bash
python3 tools/validate_structured_mesh_sweep.py
```

The pre-reset cases from July 2026 are stored under
`archive/test_cases_202607/`. Source-level regression tests remain in
`tests/` and should be run before a campaign is started.
