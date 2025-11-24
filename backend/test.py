import pandas as pd
from agent import interpret_and_execute
from data_tools import load_dataset
from config import MODEL_NAME

def test_basic_operations():
    """Test basic DataFrame operations"""
    print("\nTesting basic operations...")
    
    df = load_dataset("dataset/tips.csv")
    if isinstance(df, str):
        print(f"Error loading dataset: {df}")
        return
    
    test_cases = [
        "show first 5 rows",
        "calculate mean of tip column",
        "show summary statistics",
        "create histogram of total_bill"
    ]
    
    for test in test_cases:
        print(f"\nTesting: {test}")
        result, code = interpret_and_execute(test, df)
        print(f"Generated code: {code}")
        print(f"Result: {result}")

def test_complex_operations():
    """Test more complex data analysis operations"""
    print("\nTesting complex operations...")
    
    df = load_dataset("dataset/tips.csv")
    if isinstance(df, str):
        print(f"Error loading dataset: {df}")
        return
    
    test_cases = [
        "show average tip by day and gender",
        "create scatter plot of total_bill vs tip colored by gender",
        "find correlation between total_bill and tip",
        "show percentage of customers by day"
    ]
    
    for test in test_cases:
        print(f"\nTesting: {test}")
        result, code = interpret_and_execute(test, df)
        print(f"Generated code: {code}")
        print(f"Result: {result}")

def test_error_handling():
    """Test error handling capabilities"""
    print("\nTesting error handling...")
    
    df = load_dataset("dataset/tips.csv")
    if isinstance(df, str):
        print(f"Error loading dataset: {df}")
        return
    
    test_cases = [
        "show column that doesn't exist",
        "calculate mean of non-numeric column",
        "create plot without required parameters"
    ]
    
    for test in test_cases:
        print(f"\nTesting: {test}")
        result, code = interpret_and_execute(test, df)
        print(f"Generated code: {code}")
        print(f"Result: {result}")

def main():
    print(f"Testing data analysis agent with model: {MODEL_NAME}")
    
    # Run all tests
    test_basic_operations()
    test_complex_operations()
    test_error_handling()
    
    print("\nAll tests completed!")

if __name__ == "__main__":
    main()
    
#this block of code is used to test the model
#it prints the response from the model
#the response is then used to train the agent


