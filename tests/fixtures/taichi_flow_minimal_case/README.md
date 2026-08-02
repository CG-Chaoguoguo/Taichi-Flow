# Taichi-Flow minimal case

The 2x2 ASCII DEM and zero-rainfall numeric CSV are deterministic fixtures for
the API and one real Taichi execution. The rainfall file intentionally has no
header because the production RainfallReader consumes numeric rows directly.
This is not a numerical parity oracle and does not change solver semantics.
