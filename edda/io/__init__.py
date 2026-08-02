"""I/O utilities for EDDA-Taichi."""

from .dem_reader import DEMReader, read_ascii_grid
from .nodata_handler import NoDataHandler, detect_nodata_value, fill_nodata_auto
from .result_exporter import ResultExporter, export_results
from .rainfall_reader import RainfallReader, read_rainfall_csv, generate_design_storm
from .zone_reader import ZoneReader
from .hydrograph_exporter import (
    HydrographAccumulator,
    HydrographMonitorSample,
    compare_hydrograph_outputs,
    parse_hydrograph_cell_file,
    parse_hydrograph_output,
    write_hydrograph_file,
)
from .stormdrain_reader import (
    STORMDRAIN_RUNTIME_FLAG,
    StormdrainTopologyError,
    load_stormdrain_topology,
    run_stormdrain_runtime_consumer,
    stormdrain_runtime_enabled,
)

__all__ = [
    'DEMReader',
    'read_ascii_grid',
    'NoDataHandler',
    'detect_nodata_value',
    'fill_nodata_auto',
    'ResultExporter',
    'export_results',
    'RainfallReader',
    'read_rainfall_csv',
    'generate_design_storm',
    'ZoneReader',
    'HydrographAccumulator',
    'HydrographMonitorSample',
    'compare_hydrograph_outputs',
    'parse_hydrograph_cell_file',
    'parse_hydrograph_output',
    'write_hydrograph_file',
    'STORMDRAIN_RUNTIME_FLAG',
    'StormdrainTopologyError',
    'load_stormdrain_topology',
    'run_stormdrain_runtime_consumer',
    'stormdrain_runtime_enabled',
]
