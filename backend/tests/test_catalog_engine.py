import pandas as pd
import pytest
from src.core.tools.catalog import CatalogEngine

def test_catalog_engine_detection():
    data = {
        "user_id": ["8e3f-...", "a1b2-...", "c3d4-..."],
        "email_address": ["test@example.com", "user@domain.org", "invalid-email"],
        "transaction_amount": ["$10.00", "$50.50", "$100.00"],
        "signup_date": ["2023-01-01", "2023-02-15", "2024-12-31"],
        "latitude": [40.7128, 34.0522, 51.5074],
        "generic_text": ["hello", "world", "data"]
    }
    df = pd.DataFrame(data)
    
    catalog = CatalogEngine.analyze(df)
    
    # Assertions
    cols = catalog["columns"]
    assert cols["user_id"]["semantic_type"] == "identifier"
    assert cols["email_address"]["semantic_type"] == "email"
    assert cols["transaction_amount"]["semantic_type"] == "financial"
    assert cols["signup_date"]["semantic_type"] == "temporal"
    assert cols["latitude"]["semantic_type"] == "geospatial"
    assert cols["generic_text"]["semantic_type"] == "generic"
    
    assert catalog["global_quality"]["completeness_score"] == 100.0

if __name__ == "__main__":
    test_catalog_engine_detection()
    print("CatalogEngine verification passed!")
