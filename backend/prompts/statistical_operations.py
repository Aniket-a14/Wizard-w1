STATISTICAL_EXAMPLES = [
    # Basic Statistics
    {
        "task": "calculate mean of tip column",
        "code": "df['tip'].mean()"
    },
    {
        "task": "find median total bill",
        "code": "df['total_bill'].median()"
    },
    {
        "task": "calculate variance of tips",
        "code": "df['tip'].var()"
    },
    {
        "task": "show quartiles of total bill",
        "code": "df['total_bill'].quantile([0.25, 0.5, 0.75])"
    },
    
    # Advanced Statistics
    {
        "task": "calculate skewness of tips",
        "code": "df['tip'].skew()"
    },
    {
        "task": "find kurtosis of total bills",
        "code": "df['total_bill'].kurtosis()"
    },
    {
        "task": "calculate covariance of bill and tip",
        "code": "df[['total_bill', 'tip']].cov()"
    },
    
    # Aggregations
    {
        "task": "show all statistics for tip column",
        "code": "df['tip'].agg(['mean', 'median', 'std', 'var', 'min', 'max'])"
    },
    {
        "task": "calculate rolling average of tips",
        "code": "df['tip'].rolling(window=3).mean()"
    },
    {
        "task": "find cumulative sum of bills",
        "code": "df['total_bill'].cumsum()"
    },
    
    # Group Statistics
    {
        "task": "show statistics by day",
        "code": "df.groupby('day')['tip'].describe()"
    },
    {
        "task": "calculate z-scores of tips",
        "code": "(df['tip'] - df['tip'].mean()) / df['tip'].std()"
    },
    {
        "task": "calculate mean of total_bill",
        "code": "df['total_bill'].mean()"
    },
    {
        "task": "find sum of tips",
        "code": "df['tip'].sum()"
    },
    {
        "task": "get correlation between tip and total_bill",
        "code": "df['tip'].corr(df['total_bill'])"
    },
    {
        "task": "show summary statistics",
        "code": "df.describe()"
    },
    {
        "task": "perform bootstrap analysis",
        "code": "bootstrap_means = [df['tip'].sample(n=len(df), replace=True).mean() for _ in range(1000)]\npd.Series(bootstrap_means).describe()"
    },
    {
        "task": "calculate moving average with exponential weights",
        "code": "df['exp_weighted_avg'] = df['tip'].ewm(span=7, adjust=False).mean()"
    },
    {
        "task": "perform multiple hypothesis testing",
        "code": "from statsmodels.stats.multitest import multipletests\np_values = [stats.ttest_ind(group['tip'], df['tip']).pvalue for name, group in df.groupby('day')]"
    },
    {
        "task": "calculate robust statistics",
        "code": "from scipy.stats import trim_mean\n{'median': df['tip'].median(), 'trimmed_mean': trim_mean(df['tip'], 0.1), 'mad': stats.median_abs_deviation(df['tip'])}"
    }
] 