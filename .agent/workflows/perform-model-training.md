---
description: Train a Machine Learning model with rigor and validation
---
# Model Training Workflow

This workflow guides the agent to train a predictive model following best practices.

1.  **Data Preparation**
    -   **Handle Missing Values**: Impute (Mean/Median for numeric, Mode/Constant for categorical) or drop.
    -   **Encode Categoricals**: One-Hot Encoding (low cardinality) or Label/Target Encoding (high cardinality).
    -   **Feature Scaling**: StandardScaler or MinMaxScaler (crucial for distance-based algorithms).
    -   **Split Data**: Train-Test Split (80/20 or 70/30). Ensure stratification for classification tasks.

2.  **Baseline Model**
    -   Train a simple baseline (e.g., Logistic Regression or DummyClassifier).
    -   Establish a performance floor to beat.

3.  **Model Selection & Training**
    -   Choose appropriate algorithms (Random Forest, Gradient Boosting, etc.).
    -   **Cross-Validation**: Use K-Fold Cross-Validation (e.g., 5-fold) to assess stability.
    -   **Hyperparameter Tuning**: Use GridSearchCV or RandomizedSearchCV to optimize parameters.

4.  **Model Evaluation**
    -   **Metrics**:
        -   Classification: Accuracy, Precision, Recall, F1-Score, ROC-AUC.
        -   Regression: MAE, MSE, RMSE, R2.
    -   **Residual Analysis**: Check if errors are normally distributed (Regression).
    -   **Confusion Matrix**: Visualize misclassifications (Classification).

5.  **Feature Importance**
    -   Extract and plot Feature Importance (Tree-based models) or Coefficients (Linear models).
    -   Identify top drivers of the prediction.

6.  **Final Report**
    -   Summarize the best model's performance.
    -   Compare against baseline.
    -   Provide recommendations for deployment or further improvement.
