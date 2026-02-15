import pandas as pd
import io
import os
import sys

# Set up paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.agent.flow import science_agent

def test_full_cleaning_workflow():
    # 1. Create a "messy" dataset
    data = {
        "date_col": ["2023-01-01", "2023-01-02", "Invalid Date"],
        "price_col": ["$10.0", "$20.5", "Free"],
        "name_col": ["  aniket  ", "BOB  ", " charlie"]
    }
    df = pd.DataFrame(data)
    
    print("--- Original Data ---")
    print(df)
    
    # 2. Run Cleaning Workflow
    cleaned_df, catalog, summary = science_agent.clean_dataset(df)
    
    print("\n--- Cleaning Summary ---")
    print(summary)
    
    print("\n--- Catalog Semantic Types ---")
    for col, meta in catalog["columns"].items():
        print(f"{col}: {meta['semantic_type']}")
        
    print("\n--- Cleaned Data ---")
    print(cleaned_df)

if __name__ == "__main__":
    test_full_cleaning_workflow()
