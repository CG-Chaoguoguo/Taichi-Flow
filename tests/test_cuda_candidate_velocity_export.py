from __future__ import annotations

import numpy as np

from tools.run_cuda_candidate_case import apply_flow_velocity_output_state, velocity_fields


class _FakeField:
    def __init__(self, values: np.ndarray) -> None:
        self._values = values

    def to_numpy(self) -> np.ndarray:
        return self._values


class _FakeFields:
    def __init__(self, source_entry: np.ndarray) -> None:
        self.depo_velocity_source_entry = _FakeField(source_entry)


def test_cuda_candidate_flow_velocity_matches_fortran_writer_half_first_four_directions():
    fv = np.zeros((2, 1, 8), dtype=np.float64)
    fv[0, 0, 4] = 7.0
    fv[0, 0, 5] = -8.0
    fv[1, 0, 0] = 2.0
    fv[1, 0, 1] = -4.0
    fv[1, 0, 2] = 6.0
    fv[1, 0, 3] = -8.0
    fv[1, 0, 7] = 100.0

    fields = velocity_fields({"fv_fortran": fv})

    assert fields["Flow_velocity"].shape == (1, 2)
    assert fields["Flow_velocity"][0, 0] == 0.0
    assert fields["Flow_velocity"][0, 1] == 10.0
    assert fields["Flow_velocity_5"][0, 0] == 7.0
    assert fields["Flow_velocity_8"][0, 1] == 100.0


def test_cuda_candidate_flow_velocity_output_state_can_use_source_entry_writer_state():
    post = np.zeros((1, 1, 8), dtype=np.float64)
    source = np.zeros((1, 1, 8), dtype=np.float64)
    post[0, 0, :4] = [1.0, -1.0, 1.0, -1.0]
    source[0, 0, :4] = [2.0, -4.0, 6.0, -8.0]
    arrays = velocity_fields({"fv_fortran": post})

    replaced = apply_flow_velocity_output_state(arrays, _FakeFields(source), "source_entry")

    assert replaced == [
        "Flow_velocity",
        "Flow_velocity_1",
        "Flow_velocity_2",
        "Flow_velocity_3",
        "Flow_velocity_4",
        "Flow_velocity_5",
        "Flow_velocity_6",
        "Flow_velocity_7",
        "Flow_velocity_8",
    ]
    assert arrays["Flow_velocity"][0, 0] == 10.0
    assert arrays["Flow_velocity_1"][0, 0] == 2.0
    assert arrays["Flow_velocity_4"][0, 0] == -8.0
