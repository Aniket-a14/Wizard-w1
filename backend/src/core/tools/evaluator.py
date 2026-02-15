from typing import Dict, List, Any
import numpy as np
from ...utils.logging import logger

class Evaluator:
    """
    Evaluates agent performance against ground truth and scientific best practices.
    Implements 'AI-Assisted Judges' pattern.
    """

    @staticmethod
    def score_execution(result: str, expected_snippet: str = None) -> Dict[str, Any]:
        """
        Heuristic-based scoring of an execution result.
        """
        score = 100
        deductions = []

        # 1. Error Check
        if "Error" in result:
            score -= 50
            deductions.append("Execution error detected.")

        # 2. Content Check
        if expected_snippet and expected_snippet.lower() not in result.lower():
            score -= 30
            deductions.append(f"Expected snippet '{expected_snippet}' missing from output.")

        # 3. Scientific Rigour Check
        scientific_keywords = ["mean", "distribution", "variance", "p-value", "significant"]
        keyword_matches = sum(1 for kw in scientific_keywords if kw in result.lower())
        if keyword_matches == 0:
            score -= 10
            deductions.append("Low scientific terminology in response.")

        return {
            "score": max(0, score),
            "deductions": deductions,
            "status": "PASS" if score >= 70 else "FAIL"
        }

    @staticmethod
    def evaluate_code_quality(code: str) -> Dict[str, Any]:
        """
        Checks code for best practices (imports, comments, safety).
        """
        is_clean = True
        warnings = []
        
        prohibited = ["exec(", "eval(", "os.system", "subprocess"]
        for p in prohibited:
            if p in code:
                is_clean = False
                warnings.append(f"Security Warning: Prohibited call '{p}' detected.")

        if "import" not in code:
            warnings.append("No imports detected (might be incomplete).")

        return {
            "is_clean": is_clean,
            "warnings": warnings,
            "quality_rating": "High" if is_clean and not warnings else "Low"
        }
