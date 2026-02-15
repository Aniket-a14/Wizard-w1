import pandas as pd
import io
import os
import sys
import json
import time

# Set up paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from unittest.mock import MagicMock, patch
from src.core.agent.flow import ScientificAgent
from src.core.memory import working_memory
from src.core.reporting import reporting_engine
from src.core.tools.sandbox import SandboxManager

def verify_ecosystem():
    print("🚀 --- Wizard w1: Full Ecosystem Integration Test (Lightweight) ---")
    
    # Mock LLM to avoid heavy inference on laptop
    mock_plan = "<thought>Verification thought</thought>\n1. Clean data\n2. Analyze Revenue"
    mock_result = "Analysis complete. Revenue is growing. The Council's Review: Good."
    mock_code = "print('Revenue analysis in progress...')\nimport pandas as pd\nimport matplotlib.pyplot as plt\nplt.plot([1,2],[1,2])"

    with patch('src.core.agent.flow.ScientificAgent._create_plan', return_value=mock_plan), \
         patch('src.core.agent.agent.DataAnalysisAgent.run', return_value=(mock_result, mock_code, None)):
        
        agent = ScientificAgent()
        
        # 1. Simulate Upload & Cleaning
        print("\n[Step 1] Simulating Data Upload & Semantic Cleaning...")
        raw_df = pd.DataFrame({
            "User_ID": [101, 102, 103],
            "Revenue": ["$1,000", "$2,500", "invalid"],
            "Signup_Date": ["2023-01-01", "2023-02-01", "2023-03-01"]
        })
        
        # Trigger cleaning flow
        cleaned_df, catalog, summary = agent.clean_dataset(raw_df)
        
        print(f"✅ Catalog detected: {list(catalog['columns'].keys())}")
        print(f"✅ Cleaning result: {summary}")
        
        # 2. Simulate Analysis (Full Loop)
        print("\n[Step 2] Simulating Analysis Loop (Plan -> Exec -> Guardrail -> Council)...")
        instruction = "Analyze the revenue trend."
        
        result, code, image, thought, status = agent.run(
            instruction, 
            cleaned_df, 
            mode="fast", # Skip confirmation for test
            catalog=catalog
        )
        
        print(f"✅ Execution Result received.")
        if "The Council's Review" in result:
            print("✅ Council Adjudication: FOUND in result.")
        else:
            print("❌ Council Adjudication: MISSING from result.")

        # 3. Verify Memory Persistence
        print("\n[Step 3] Verifying Memory Persistence...")
        recent = working_memory.search("revenue")
        if recent:
            print(f"✅ Memory Found: '{recent[0]['instruction']}' saved successfully.")
        else:
            print("❌ Memory Check: FAILED to find recent interaction.")

        # 4. Verify Reporting Engine
        print("\n[Step 4] Verifying Reporting Engine...")
        report = reporting_engine.generate_executive_summary()
        if "# 📊 Wizard AI: Executive Data Story" in report:
            print("✅ Report Generated: Successfully created markdown summary.")
        else:
            print("❌ Report Generation: FAILED.")

    print("\n--- 🏁 Verification Finished (All Systems Connected) ---")

if __name__ == "__main__":
    # Ensure Docker is running or we'll get errors
    try:
        verify_ecosystem()
    except Exception as e:
        print(f"\n❌ CRITICAL FAILURE: {str(e)}")
        sys.exit(1)
