MACHINE_LEARNING_EXAMPLES = [
    # Data Preprocessing
    {
        "task": "scale numeric features",
        "code": "from sklearn.preprocessing import StandardScaler\nscaler = StandardScaler()\nX_scaled = scaler.fit_transform(df[['total_bill', 'tip']])"
    },
    {
        "task": "normalize features",
        "code": "from sklearn.preprocessing import MinMaxScaler\nscaler = MinMaxScaler()\nX_normalized = scaler.fit_transform(df[['total_bill', 'tip']])"
    },
    
    # Feature Selection
    {
        "task": "select features by correlation",
        "code": "correlation = df.corr()['tip'].abs().sort_values(ascending=False)\nselected_features = correlation[correlation > 0.3].index"
    },
    {
        "task": "remove highly correlated features",
        "code": "corr_matrix = df.corr().abs()\nupper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))\nto_drop = [column for column in upper.columns if any(upper[column] > 0.95)]"
    },

    # Model Training
    {
        "task": "train linear regression",
        "code": "from sklearn.linear_model import LinearRegression\nmodel = LinearRegression()\nmodel.fit(X_train, y_train)"
    },
    {
        "task": "train random forest",
        "code": "from sklearn.ensemble import RandomForestRegressor\nrf = RandomForestRegressor(n_estimators=100)\nrf.fit(X_train, y_train)"
    },

    # Model Evaluation
    {
        "task": "calculate regression metrics",
        "code": "from sklearn.metrics import mean_squared_error, r2_score\nmse = mean_squared_error(y_test, y_pred)\nr2 = r2_score(y_test, y_pred)"
    },
    {
        "task": "perform cross validation",
        "code": "from sklearn.model_selection import cross_val_score\nscores = cross_val_score(model, X, y, cv=5)"
    },

    # Model Tuning
    {
        "task": "grid search hyperparameters",
        "code": "from sklearn.model_selection import GridSearchCV\nparams = {'n_estimators': [100, 200], 'max_depth': [10, 20]}\ngrid = GridSearchCV(RandomForestRegressor(), params, cv=5)\ngrid.fit(X, y)"
    },
    {
        "task": "random search hyperparameters",
        "code": "from sklearn.model_selection import RandomizedSearchCV\nparams = {'n_estimators': range(100, 500), 'max_depth': range(10, 50)}\nrandom = RandomizedSearchCV(RandomForestRegressor(), params, n_iter=10)\nrandom.fit(X, y)"
    },

    # Feature Importance
    {
        "task": "get feature importance from random forest",
        "code": "importances = pd.DataFrame({'feature': X.columns, 'importance': rf.feature_importances_}).sort_values('importance', ascending=False)"
    },
    {
        "task": "plot feature importance",
        "code": "importances.plot(x='feature', y='importance', kind='bar')\nplt.title('Feature Importance')\nplt.tight_layout()"
    }
] 