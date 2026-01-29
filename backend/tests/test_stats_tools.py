import pytest
import pandas as pd
import numpy as np
from src.core.tools.stats import StatisticalToolkit


class TestStatsTools:
    @pytest.fixture
    def normal_df(self):
        np.random.seed(42)
        # Generate normal distribution
        data = np.random.normal(loc=0, scale=1, size=100)
        return pd.DataFrame({"val": data})

    @pytest.fixture
    def outlier_df(self):
        data = [10, 12, 11, 13, 10, 12, 1000]  # 1000 is outlier
        return pd.DataFrame({"val": data})

    def test_check_normality(self, normal_df):
        # Normal data should pass (p > 0.05 usually)
        result = StatisticalToolkit.check_normality(normal_df, "val")
        assert result["is_normal"] is True
        assert result["test_used"] == "Shapiro-Wilk"

    def test_detect_outliers_iqr(self, outlier_df):
        result = StatisticalToolkit.detect_outliers(outlier_df, "val", method="iqr")
        assert result["outlier_count"] == 1
        assert result["sample_outliers"][0] == 1000

    def test_correlation(self):
        df = pd.DataFrame(
            {
                "x": [1, 2, 3, 4, 5],
                "y": [2, 4, 6, 8, 10],  # Perfect correlation
                "z": [5, 4, 3, 2, 1],  # Perfect negative
            }
        )
        results = StatisticalToolkit.correlation_analysis(df, "x")
        print(results)

        # y should be 1.0, z should be -1.0
        assert results[0]["feature"] == "y"
        assert results[0]["correlation"] == 1.0
        assert results[0]["strength"] == "Strong"
