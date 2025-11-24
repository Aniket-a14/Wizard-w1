from typing import Union
import pandas as pd
from pathlib import Path

def load_dataset(file_path: Union[str, Path]) -> Union[pd.DataFrame, str]:
    """
    Load a CSV file into a Pandas DataFrame with validation.
    
    Args:
        file_path: Path to the CSV file
        
    Returns:
        Either a DataFrame if successful, or an error message string
    """
    try:
        path = Path(file_path)
        
        # Validate file existence
        if not path.exists():
            return f"Error: File '{file_path}' does not exist"
            
        # Validate file extension
        if path.suffix.lower() != '.csv':
            return f"Error: File '{file_path}' is not a CSV file"
            
        # Try to read the file
        df = pd.read_csv(path)
        
        # Validate that the DataFrame is not empty
        if df.empty:
            return "Error: The CSV file is empty"
            
        # Basic data validation
        if df.columns.duplicated().any():
            return "Error: Dataset contains duplicate column names"
            
        return df
        
    except pd.errors.EmptyDataError:
        return "Error: The CSV file is empty"
    except pd.errors.ParserError:
        return "Error: Unable to parse the CSV file. Please check the file format"
    except Exception as e:
        return f"Error loading dataset: {e}"

#this block of code is used to load the dataset from the csv file
#it returns the dataframe if successful, or an error message as a string
#the dataframe is then used in the agent.py file to execute the code



