import pytest
import pandas as pd
import numpy as np
import os
import sys
import matplotlib

# Force Agg backend before importing pyplot
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Ensure backend can import its modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def load_dataset(file_path):
    """Simple helper to load dataset for tests."""
    try:
        if not os.path.exists(file_path):
            return None
        return pd.read_csv(file_path)
    except Exception:
        return None

@pytest.fixture
def empty_df():
    return pd.DataFrame()

@pytest.fixture
def simple_df():
    data = {
        'A': [1, 2, 3, 4, 5],
        'B': ['x', 'y', 'z', 'w', 'v'],
        'C': [0.1, 0.2, 0.3, 0.4, 0.5]
    }
    return pd.DataFrame(data)

@pytest.fixture
def tips_df():
    # Try loading from standard location, fallback to creating dummy if file missing (for CI/portability)
    dataset_path = os.path.join(os.path.dirname(__file__), '..', 'dataset', 'tips.csv')
    if os.path.exists(dataset_path):
        df = load_dataset(dataset_path)
        if isinstance(df, pd.DataFrame):
            return df
    
    # Fallback mock tips data
    data = {
        'total_bill': [16.99, 10.34, 21.01, 23.68, 24.59],
        'tip': [1.01, 1.66, 3.50, 3.31, 3.61],
        'sex': ['Female', 'Male', 'Male', 'Male', 'Female'],
        'smoker': ['No', 'No', 'No', 'No', 'No'],
        'day': ['Sun', 'Sun', 'Sun', 'Sun', 'Sun'],
        'time': ['Dinner', 'Dinner', 'Dinner', 'Dinner', 'Dinner'],
        'size': [2, 3, 3, 2, 4]
    }
    return pd.DataFrame(data)

@pytest.fixture
def missing_values_df():
    data = {
        'A': [1, 2, np.nan, 4],
        'B': ['x', np.nan, 'z', 'w']
    }
    return pd.DataFrame(data)
