"""Tests for temperature unit conversion functions."""

import math

from roastmaster.display.units import c_to_f, f_to_c, f_to_c_delta


class TestFToC:
    def test_f_to_c_freezing(self):
        assert f_to_c(32.0) == 0.0

    def test_f_to_c_boiling(self):
        assert f_to_c(212.0) == 100.0


class TestFToCDelta:
    def test_f_to_c_delta_zero(self):
        assert f_to_c_delta(0.0) == 0.0

    def test_f_to_c_delta_ror(self):
        result = f_to_c_delta(10.0)
        assert math.isclose(result, 5.5556, rel_tol=1e-3)


class TestCToFRoundtrip:
    def test_c_to_f_roundtrip(self):
        for temp_f in [32.0, 100.0, 212.0, 350.0, 450.0]:
            assert math.isclose(c_to_f(f_to_c(temp_f)), temp_f, rel_tol=1e-9)
