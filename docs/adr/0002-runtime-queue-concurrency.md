# Serialize runs per project and coordinate the process-global Taichi runtime

Each Project may execute one Simulation Run at a time, while compatible projects may run concurrently up to `TAICHI_FLOW_MAX_CONCURRENT_PROJECTS` (default 2). Admission is additionally gated by the normalized Taichi initialization signature because Taichi runtime initialization and reset are process-global; incompatible signatures wait until active sessions reach zero rather than reinitializing under live work.
