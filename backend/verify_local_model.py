print("Starting verification script...")
import pandas as pd
print("Imported pandas")
from agent import interpret_and_execute
print("Imported agent")
from config import MODEL_TYPE
print(f"Imported config, MODEL_TYPE: {MODEL_TYPE}")

# Create a dummy dataframe
df = pd.DataFrame({
    'A': [1, 2, 3, 4, 5],
    'B': [10, 20, 30, 40, 50]
})

# Test instruction
instruction = "Calculate the mean of column A"
print(f"Instruction: {instruction}")

try:
    result, code = interpret_and_execute(instruction, df)
    print(f"Generated Code: {code}")
    print(f"Result: {result}")
    print("Verification Successful!")
except Exception as e:
    print(f"Verification Failed: {e}")
    import traceback
    traceback.print_exc()
