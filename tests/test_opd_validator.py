"""Tests for OPD marker validation."""

from __future__ import annotations

import pytest

from src.config import load_opd_markers
from src.validators.opd_validator import (
    validate_opd_markers,
    is_valid_o_code,
    is_valid_p_code,
    is_valid_d_code,
    clear_cache,
)


class TestOpdMarkerLoading:
    """Test that the real opd_markers.yml loads correctly."""

    def test_loads_without_error(self, config_dir):
        """The config opd_markers.yml should load."""
        markers = load_opd_markers(config_dir)
        assert markers is not None
        assert "O" in markers
        assert "P" in markers
        assert "D" in markers

    def test_o_codes_start_with_o_underscore(self, opd_markers):
        """All O codes must start with O_."""
        for code in opd_markers["O"]:
            assert code.startswith("O_"), f"O code '{code}' doesn't start with O_"

    def test_p_codes_start_with_p(self, opd_markers):
        """All P codes must start with P."""
        for code in opd_markers["P"]:
            assert code.startswith("P"), f"P code '{code}' doesn't start with P"

    def test_d_codes_start_with_d(self, opd_markers):
        """All D codes must start with D."""
        for code in opd_markers["D"]:
            assert code.startswith("D"), f"D code '{code}' doesn't start with D"

    def test_no_duplicate_o_codes(self, opd_markers):
        """O codes should be unique."""
        assert len(opd_markers["O"]) == len(set(opd_markers["O"])), \
            "Duplicate O codes found"

    def test_no_duplicate_p_codes(self, opd_markers):
        """P codes should be unique."""
        assert len(opd_markers["P"]) == len(set(opd_markers["P"])), \
            "Duplicate P codes found"

    def test_no_duplicate_d_codes(self, opd_markers):
        """D codes should be unique."""
        assert len(opd_markers["D"]) == len(set(opd_markers["D"])), \
            "Duplicate D codes found"

    def test_has_expected_o_codes(self, opd_markers):
        """Check that essential O codes are present."""
        required = {"O_极限", "O_导数", "O_微分方程", "O_矩阵", "O_参数估计"}
        o_set = set(opd_markers["O"])
        missing = required - o_set
        assert not missing, f"Missing expected O codes: {missing}"

    def test_has_expected_p_codes(self, opd_markers):
        """Check that essential P codes are present."""
        required = {"P11_正向思路", "P2_反证思路", "P3_数学归纳", "P6_分类讨论"}
        p_set = set(opd_markers["P"])
        missing = required - p_set
        assert not missing, f"Missing expected P codes: {missing}"

    def test_has_expected_d_codes(self, opd_markers):
        """Check that essential D codes are present."""
        required = {"D21_观察研究对象", "D22_转换等价表述", "D43_数形结合", "D41_利用已知结论"}
        d_set = set(opd_markers["D"])
        missing = required - d_set
        assert not missing, f"Missing expected D codes: {missing}"


class TestValidateOpdMarkers:
    """Test the validator function."""

    def test_validate_real_markers_passes(self, config_dir):
        """The real OPD markers should pass validation."""
        clear_cache()
        result = validate_opd_markers(config_dir)
        assert result["valid"], f"Validation failed: {result['errors']}"
        assert result["o_count"] > 0
        assert result["p_count"] > 0
        assert result["d_count"] > 0

    def test_validate_nonexistent_file(self, tmp_path):
        """A nonexistent config dir should return invalid."""
        clear_cache()
        result = validate_opd_markers(tmp_path)
        assert not result["valid"]


class TestOpdCodeLookup:
    """Test the is_valid_o/p/d_code functions."""

    def test_valid_o_code(self, config_dir):
        """A known O code should return True."""
        clear_cache()
        assert is_valid_o_code("O_极限", config_dir)

    def test_invalid_o_code(self, config_dir):
        """An unknown O code should return False."""
        clear_cache()
        assert not is_valid_o_code("O_不存在的代码", config_dir)

    def test_non_o_prefix_code(self, config_dir):
        """A code not starting with O_ should return False."""
        clear_cache()
        assert not is_valid_o_code("P11_正向思路", config_dir)
        assert not is_valid_o_code("not_a_code", config_dir)

    def test_valid_p_code(self, config_dir):
        """A known P code should return True."""
        clear_cache()
        assert is_valid_p_code("P11_正向思路", config_dir)
        assert is_valid_p_code("P2_反证思路", config_dir)

    def test_invalid_p_code(self, config_dir):
        """An unknown P code should return False."""
        clear_cache()
        assert not is_valid_p_code("P_不存在", config_dir)

    def test_valid_d_code(self, config_dir):
        """A known D code should return True."""
        clear_cache()
        assert is_valid_d_code("D22_转换等价表述", config_dir)
        assert is_valid_d_code("D43_数形结合", config_dir)

    def test_invalid_d_code(self, config_dir):
        """An unknown D code should return False."""
        clear_cache()
        assert not is_valid_d_code("D_不存在", config_dir)
