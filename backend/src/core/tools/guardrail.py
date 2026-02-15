from typing import Tuple
import re
from ...utils.logging import logger

class GuardrailAgent:
    """
    Scans generated code for security risks, malformed syntax, 
    and alignment with user safety policies.
    """

    PROHIBITED_PATTERNS = [
        (r"os\.", "OS module access"),
        (r"subprocess\.", "Subprocess execution"),
        (r"eval\(", "Dangerous eval() call"),
        (r"exec\(", "Dangerous exec() call"),
        (r"socket\.", "Network socket access"),
        (r"requests\.", "Network request attempt"),
        (r"open\(", "Direct file system access")
    ]

    @classmethod
    def scan(cls, code: str) -> Tuple[bool, str]:
        """
        Scans code and returns (is_safe, reason).
        """
        for pattern, reason in cls.PROHIBITED_PATTERNS:
            if re.search(pattern, code):
                logger.warning("Guardrail Triggered", reason=reason)
                return False, f"Guardrail Violation: {reason} is prohibited."
        
        # Check for empty code
        if not code.strip():
            return False, "Code generation appeared to fail (empty response)."

        return True, "Safe"

    @classmethod
    def audit_scientific_alignment(cls, plan: str, code: str) -> Tuple[bool, str]:
        """
        Verifies if the code actually attempts to execute the plan.
        """
        # Basic keyword alignment
        plan_keywords = re.findall(r"\b\w{4,}\b", plan.lower())
        code_lower = code.lower()
        
        matches = [kw for kw in plan_keywords if kw in code_lower]
        if len(matches) < 2 and len(plan_keywords) > 5:
            return False, "Code does not seem aligned with the proposed plan."
            
        return True, "Aligned"
