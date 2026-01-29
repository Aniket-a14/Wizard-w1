---
description: Perform comprehensive Exploratory Data Analysis (EDA) on a dataset
---
# Exploratory Data Analysis (EDA) Workflow

This workflow guides the agent to perform a rigorous statistical analysis of a dataset.

1.  **Load and Inspect Data**
    -   Load the dataset (CSV/Parquet).
    -   Display the shape, columns, and data types.
    -   Display the first 5 rows to understand the structure.

2.  **Data Quality Check**
    -   Check for missing values (`df.isnull().sum()`).
    -   Check for duplicate rows.
    -   Identify potential data type mismatches (e.g., numeric columns stored as objects).

3.  **Univariate Analysis (Distribution)**
    -   For **Numeric Columns**:
        -   Calculate summary statistics (mean, median, std, min, max).
        -   **Safety Check**: Use `stats.check_normality(df, col)` to test for Gaussian distribution.
        -   **Safety Check**: Use `stats.detect_outliers(df, col)` using IQR or Z-Score.
        -   Plot Histograms (with KDE) and Boxplots.
    -   For **Categorical Columns**:
        -   Calculate value counts.
        -   Plot Bar Charts or Pie Charts (if low cardinality).

4.  **Bivariate Analysis (Relationships)**
    -   **Numeric vs Numeric**:
        -   Calculate Correlation Matrix (Pearson/Spearman).
        -   Plot Heatmap of correlations.
        -   Plot Scatter Plots for highly correlated pairs.
    -   **Numeric vs Categorical**:
        -   Perform GroupBy aggregations (mean/median).
        -   Plot Boxplots or Violin Plots split by category.
    -   **Categorical vs Categorical**:
        -   Create Cross-Tabulations (Contingency Tables).
        -   Perform Chi-Square Test of Independence (if applicable).

5.  **Multi-variate Analysis**
    -   Use Pairplots (small datasets) or 3D Scatter Plots (if relevant).
    -   Dimensionality Reduction (PCA/t-SNE) for high-dimensional data visualization.

6.  **Summary and Insights**
    -   Synthesize findings into a text summary.
    -   Highlight data quality issues, key trends, and potential anomalies.
