TIME_SERIES_EXAMPLES = [
    # Date Processing
    {
        "task": "convert to datetime index",
        "code": "df.index = pd.to_datetime(df.index)"
    },
    {
        "task": "resample daily data to monthly",
        "code": "df.resample('M').mean()"
    },

    # Time Series Components
    {
        "task": "calculate rolling statistics",
        "code": "df['rolling_mean'] = df['value'].rolling(window=7).mean()"
    },
    {
        "task": "decompose time series",
        "code": "from statsmodels.tsa.seasonal import seasonal_decompose\ndecomposition = seasonal_decompose(df['value'], period=12)"
    },

    # Forecasting
    {
        "task": "create time series features",
        "code": "df['year'] = df.index.year\ndf['month'] = df.index.month\ndf['day'] = df.index.day"
    },
    {
        "task": "shift data for forecasting",
        "code": "df['lag1'] = df['value'].shift(1)\ndf['lag7'] = df['value'].shift(7)"
    }
] 