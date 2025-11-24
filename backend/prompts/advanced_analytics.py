ADVANCED_EXAMPLES = [
    # Time Series Analysis
    {
        "task": "calculate rolling mean with 7-day window",
        "code": "df['total_bill'].rolling(window=7).mean()"
    },
    {
        "task": "compute exponential moving average",
        "code": "df['tip'].ewm(span=5).mean()"
    },
    
    # Statistical Tests
    {
        "task": "perform t-test between smoker and non-smoker tips",
        "code": "from scipy import stats\nstats.ttest_ind(df[df['smoker']=='Yes']['tip'], df[df['smoker']=='No']['tip'])"
    },
    {
        "task": "check normality of tips",
        "code": "from scipy import stats\nstats.normaltest(df['tip'])"
    },
    
    # Feature Engineering
    {
        "task": "create tip percentage feature",
        "code": "df['tip_pct'] = (df['tip'] / df['total_bill'] * 100).round(2)"
    },
    {
        "task": "bin total bills into categories",
        "code": "pd.qcut(df['total_bill'], q=4, labels=['Low', 'Medium', 'High', 'Very High'])"
    },
    
    # Machine Learning Prep
    {
        "task": "prepare features for modeling",
        "code": "X = pd.get_dummies(df[['total_bill', 'size', 'day', 'time']])"
    },
    {
        "task": "split data into train and test",
        "code": "from sklearn.model_selection import train_test_split\nX_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)"
    },
    
    # Advanced Statistical Analysis
    {
        "task": "calculate correlation matrix",
        "code": "df.corr()"
    },
    {
        "task": "perform chi-square test",
        "code": "from scipy.stats import chi2_contingency\nchi2_contingency(pd.crosstab(df['col1'], df['col2']))"
    },
    {
        "task": "calculate confidence intervals",
        "code": "from scipy import stats\nstats.t.interval(0.95, len(df)-1, loc=df['column'].mean(), scale=stats.sem(df['column']))"
    },
    {
        "task": "create interaction features",
        "code": "df['interaction'] = df['col1'] * df['col2']"
    },
    {
        "task": "bin continuous variable",
        "code": "pd.cut(df['column'], bins=[0, 25, 50, 75, 100], labels=['Low', 'Medium', 'High', 'Very High'])"
    },
    {
        "task": "encode categorical variables",
        "code": "pd.get_dummies(df['category_column'], prefix='cat')"
    },
    # Outlier Detection
    {
        "task": "detect outliers using IQR",
        "code": "Q1 = df['tip'].quantile(0.25)\nQ3 = df['tip'].quantile(0.75)\nIQR = Q3 - Q1\noutliers = df[(df['tip'] < Q1 - 1.5*IQR) | (df['tip'] > Q3 + 1.5*IQR)]"
    },
    {
        "task": "find z-score outliers",
        "code": "from scipy import stats\nz_scores = stats.zscore(df['tip'])\noutliers = df[abs(z_scores) > 3]"
    },

    # Advanced Statistical Tests
    {
        "task": "perform ANOVA test",
        "code": "from scipy import stats\nstats.f_oneway(df[df['day']=='Sun']['tip'], df[df['day']=='Sat']['tip'], df[df['day']=='Fri']['tip'])"
    },
    {
        "task": "run Shapiro-Wilk normality test",
        "code": "from scipy import stats\nstats.shapiro(df['tip'])"
    },
    {
        "task": "calculate Spearman correlation",
        "code": "df[['tip', 'total_bill']].corr(method='spearman')"
    },

    # Machine Learning Features
    {
        "task": "standardize numeric features",
        "code": "from sklearn.preprocessing import StandardScaler\nscaler = StandardScaler()\ndf[['tip', 'total_bill']] = scaler.fit_transform(df[['tip', 'total_bill']])"
    },
    {
        "task": "create polynomial features",
        "code": "from sklearn.preprocessing import PolynomialFeatures\npoly = PolynomialFeatures(degree=2)\npoly_features = poly.fit_transform(df[['total_bill', 'size']])"
    },
    {
        "task": "encode ordinal categories",
        "code": "from sklearn.preprocessing import OrdinalEncoder\nord_enc = OrdinalEncoder()\ndf['day_encoded'] = ord_enc.fit_transform(df[['day']])"
    },
    {
        "task": "calculate tip percentage",
        "code": "df['tip_percent'] = (df['tip'] / df['total_bill']) * 100"
    },
    {
        "task": "find average tip by gender and smoker",
        "code": "df.groupby(['Gender', 'smoker'])['tip'].mean()"
    },
    {
        "task": "perform multivariate analysis",
        "code": "from scipy import stats\nstats.multivariate_normal(mean=df[['tip', 'total_bill']].mean(), cov=df[['tip', 'total_bill']].cov())"
    },
    {
        "task": "create custom aggregation pipeline",
        "code": "df.groupby('day').agg({'tip': ['mean', 'std', lambda x: x.quantile(0.75)], 'total_bill': ['sum', 'count']})"
    },
    {
        "task": "detect outliers using isolation forest",
        "code": "from sklearn.ensemble import IsolationForest\niforest = IsolationForest(contamination=0.1)\ndf['outliers'] = iforest.fit_predict(df[['tip', 'total_bill']])"
    },
    {
        "task": "create rolling correlation",
        "code": "df['rolling_corr'] = df['tip'].rolling(window=10).corr(df['total_bill'])"
    }
] 