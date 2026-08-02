"""
Physics modules for EDDA simulation.

This package contains the core physics models:
- hydrology: Green-Ampt infiltration model
- stability: Infinite slope stability analysis
- rheology: Flow rheology (Manning and quadratic models)
- erosion: Bed erosion model
- deposition: Sediment deposition model
"""

from edda.physics.hydrology import HydrologyModel
from edda.physics.stability import StabilityModel
from edda.physics.rheology import RheologyModel
from edda.physics.erosion import ErosionModel
from edda.physics.deposition import DepositionModel

__all__ = [
    'HydrologyModel',
    'StabilityModel',
    'RheologyModel',
    'ErosionModel',
    'DepositionModel',
]
