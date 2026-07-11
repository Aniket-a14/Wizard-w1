import pandas as pd
from src.core.database import db_mgr
from src.core.tools.schema_registry import SchemaRegistry


def test_schema_registry_operations():
    # 1. Prepare sample DataFrames
    users_df = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "email": ["alice@test.com", "bob@test.com", "charlie@test.com"],
        }
    )

    orders_df = pd.DataFrame({"order_id": [101, 102, 103], "user_id": [1, 2, 1], "amount": [50.0, 120.0, 15.5]})

    # Clear registry database entries first to ensure clean state
    db_mgr.delete_schema("users.csv")
    db_mgr.delete_schema("orders.csv")

    # 2. Register
    SchemaRegistry.register_dataframe("users.csv", users_df)
    SchemaRegistry.register_dataframe("orders.csv", orders_df)

    # 3. Get Registered schemas
    schemas = db_mgr.get_schemas()
    filenames = [s["filename"] for s in schemas]
    assert "users.csv" in filenames
    assert "orders.csv" in filenames

    # Verify primary key detection heuristics
    users_schema = next(s for s in schemas if s["filename"] == "users.csv")
    orders_schema = next(s for s in schemas if s["filename"] == "orders.csv")

    assert users_schema["primary_key"] == "id"
    assert orders_schema["primary_key"] == "order_id"

    # 4. Suggestions verification
    suggestions = SchemaRegistry.get_join_suggestions()
    assert len(suggestions) >= 1

    sug = next(
        s
        for s in suggestions
        if s["file1"] == "users.csv"
        and s["file2"] == "orders.csv"
        or s["file1"] == "orders.csv"
        and s["file2"] == "users.csv"
    )
    match = sug["matching_columns"][0]

    # Assert either 'id' <-> 'user_id' or 'user_id' <-> 'id'
    assert (match["col1"] == "id" and match["col2"] == "user_id") or (
        match["col1"] == "user_id" and match["col2"] == "id"
    )

    # 5. Schema Workspace Context format verification
    context_str = SchemaRegistry.get_workspace_schema_context()
    assert "Table Name: users.csv" in context_str
    assert "Table Name: orders.csv" in context_str
    assert (
        "Link [users.csv] and [orders.csv] via:" in context_str
        or "Link [orders.csv] and [users.csv] via:" in context_str
    )

    # Cleanup
    db_mgr.delete_schema("users.csv")
    db_mgr.delete_schema("orders.csv")
