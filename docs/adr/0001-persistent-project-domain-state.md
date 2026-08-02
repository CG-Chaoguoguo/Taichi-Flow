# Persist domain state per project with SQLite and content-addressed files

Taichi-Flow stores its global project catalog under `TAICHI_FLOW_STATE_DIR`, while each Project owns `.taichi-flow/state.sqlite3` and immutable SHA-256-addressed input blobs. This keeps metadata transactional and restart-safe without placing large scientific arrays in SQLite or frontend state, and preserves project portability better than a single process-memory registry.
