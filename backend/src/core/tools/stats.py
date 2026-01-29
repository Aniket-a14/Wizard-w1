from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
from scipy import stats

class StatisticalToolkit:
    """
    A collection of robust statistical tools for the AI Agent.
    Enables 'Scientist' behavior: validating assumptions before modeling.
    """

    @staticmethod
    def check_normality(df: pd.DataFrame, column: str) -> Dict[str, Any]:
        """
        Tests if a column is normally distributed using Shapiro-Wilk (N < 5000) 
        or D'Agostino's K^2 (N >= 5000).
        """
        data = df[column].dropna()
        n = len(data)
        
        if n < 3:
            return {"is_normal": False, "p_value": None, "test": "Insufficient Data"}
        
        if n < 5000:
            # Shapiro-Wilk
            stat, p = stats.shapiro(data)
            test_name = "Shapiro-Wilk"
        else:
            # D'Agostino's K^2
            stat, p = stats.normaltest(data)
            test_name = "D'Agostino's K^2"
            
        return {
            "column": column,
            "is_normal": bool(p > 0.05),
            "p_value": p,
            "statistic": stat,
            "test_used": test_name,
            "interpretation": "Likely Normal" if p > 0.05 else "Not Normal (Reject Null)"
        }

    @staticmethod
    def detect_outliers(df: pd.DataFrame, column: str, method: str = "iqr") -> Dict[str, Any]:
        """
        Detects outliers using IQR or Z-Score.
        """
        data = df[column].dropna()
        outliers = []
        
        if method == "zscore":
            z_scores = np.abs(stats.zscore(data))
            outliers = data[z_scores > 3].tolist()
            threshold = "Z > 3"
        else:
            # IQR
            Q1 = data.quantile(0.25)
            Q3 = data.quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            outliers = data[(data < lower_bound) | (data > upper_bound)].tolist()
            threshold = f"<{lower_bound:.2f} or >{upper_bound:.2f}"
            
        return {
            "column": column,
            "method": method,
            "outlier_count": len(outliers),
            "outlier_percentage": round(len(outliers) / len(data) * 100, 2),
            "threshold_used": threshold,
            "sample_outliers": outliers[:5] # Limit output size
        }
        
    @staticmethod
    def correlation_analysis(df: pd.DataFrame, target_col: str) -> List[Dict[str, Any]]:
        """
        Finds features most correlated with the target column.
        Automatically handles numeric conversion for correlation check.
        """
        if target_col not in df.columns:
            return []
            
        # Select numeric columns
        numeric_df = df.select_dtypes(include=[np.number])
        if target_col not in numeric_df.columns:
            return [] # Target is not numeric?
            
        correlations = numeric_df.corr()[target_col].drop(target_col)
        
        # Sort by absolute correlation
        sorted_corr = correlations.abs().sort_values(ascending=False)
        
        results = []
        for col, val in sorted_corr.items():
            raw_val = correlations[col]
            results.append({
                "feature": col,
                "correlation": round(raw_val, 4),
                "strength": "Strong" if abs(raw_val) > 0.7 else "Moderate" if abs(raw_val) > 0.3 else "Weak"
            })
            
        return results[:5] # Top 5
