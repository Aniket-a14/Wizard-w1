import pandas as pd
import os
import sys

# Set up paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.tools.sandbox import SandboxManager

def verify_sandbox():
    print("--- Sandbox Verification (No LLM) ---")
    sandbox = SandboxManager()
    
    # 1. Prepare dummy data
    df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    df_bytes = buf.getvalue()
    
    # 2. Prepare code to run in sandbox
    code = """
import pandas as pd
print("Calculating sum of column A:")
print(df['A'].sum())

# Create a dummy plot
import matplotlib.pyplot as plt
plt.plot(df['A'], df['B'])
plt.title("Sandbox Plot")
"""

    print("Executing code in sandbox...")
    result, plot = sandbox.run_code(code, df_bytes)
    
    print("\n--- Sandbox Result ---")
    print(result)
    
    if plot:
        print("\n[SUCCESS] Plot base64 received (length: {})".format(len(plot)))
    else:
        print("\n[WARNING] No plot received.")

    if "6" in result:
        print("\n[SUCCESS] Calculation (1+2+3=6) verified in sandbox.")
    else:
        print("\n[FAILURE] Calculation verification failed.")

if __name__ == "__main__":
    import io # Needed for the script body
    verify_sandbox()
