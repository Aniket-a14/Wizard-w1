PANDAS_EXAMPLES = [
    # Basic Data Access
    {
        "task": "show summary statistics",
        "code": "df.describe()"
    },
    {
        "task": "select single column",
        "code": "df['tip']"
    },
    {
        "task": "select multiple columns",
        "code": "df[['tip', 'total_bill', 'day']]"
    },
    {
        "task": "get specific row by index",
        "code": "df.iloc[5]"
    },
    {
        "task": "get rows by condition",
        "code": "df.loc[df['tip'] > 5]"
    },

    # Data Filtering
    {
        "task": "filter rows where tip is greater than 5",
        "code": "df[df['tip'] > 5]"
    },
    {
        "task": "filter multiple conditions",
        "code": "df[(df['tip'] > 5) & (df['day'] == 'Sun')]"
    },
    {
        "task": "filter using isin",
        "code": "df[df['day'].isin(['Sat', 'Sun'])]"
    },
    {
        "task": "filter using string contains",
        "code": "df[df['time'].str.contains('Dinner')]"
    },
    {
        "task": "filter excluding nulls",
        "code": "df[df['tip'].notna()]"
    },

    # Data Transformation
    {
        "task": "create new column from existing",
        "code": "df['tip_percent'] = df['tip'] / df['total_bill'] * 100"
    },
    {
        "task": "apply custom function to column",
        "code": "df['tip'].apply(lambda x: 'High' if x > 5 else 'Low')"
    },
    {
        "task": "convert column type",
        "code": "df['total_bill'] = df['total_bill'].astype('float64')"
    },
    {
        "task": "rename columns",
        "code": "df.rename(columns={'tip': 'tip_amount', 'size': 'party_size'})"
    },
    {
        "task": "replace values in column",
        "code": "df['day'].replace({'Sun': 'Sunday', 'Sat': 'Saturday'})"
    },

    # Grouping and Aggregation
    {
        "task": "group by day and calculate mean tips",
        "code": "df.groupby('day')['tip'].mean()"
    },
    {
        "task": "group by multiple columns",
        "code": "df.groupby(['day', 'time'])['total_bill'].sum()"
    },
    {
        "task": "multiple aggregations",
        "code": "df.groupby('day').agg({'tip': ['mean', 'max'], 'total_bill': 'sum'})"
    },
    {
        "task": "group and transform",
        "code": "df.groupby('day')['tip'].transform('mean')"
    },
    {
        "task": "group and filter",
        "code": "df.groupby('day').filter(lambda x: x['tip'].mean() > 3)"
    },

    # Sorting and Ranking
    {
        "task": "sort by total_bill descending",
        "code": "df.sort_values('total_bill', ascending=False)"
    },
    {
        "task": "sort by multiple columns",
        "code": "df.sort_values(['day', 'tip'], ascending=[True, False])"
    },
    {
        "task": "rank tips within groups",
        "code": "df.groupby('day')['tip'].rank(method='dense')"
    },
    {
        "task": "sort index",
        "code": "df.sort_index()"
    },
    {
        "task": "get largest values",
        "code": "df.nlargest(5, 'total_bill')"
    },

    # Missing Data Handling
    {
        "task": "fill missing values with mean",
        "code": "df['tip'].fillna(df['tip'].mean())"
    },
    {
        "task": "fill missing values with method",
        "code": "df['total_bill'].fillna(method='ffill')"
    },
    {
        "task": "drop rows with any missing values",
        "code": "df.dropna()"
    },
    {
        "task": "drop rows with all missing values",
        "code": "df.dropna(how='all')"
    },
    {
        "task": "interpolate missing values",
        "code": "df['total_bill'].interpolate(method='linear')"
    },

    # Advanced Operations
    {
        "task": "pivot table creation",
        "code": "pd.pivot_table(df, values='tip', index='day', columns='time', aggfunc='mean')"
    },
    {
        "task": "melt dataframe",
        "code": "pd.melt(df, id_vars=['day'], value_vars=['tip', 'total_bill'])"
    },
    {
        "task": "create time series from index",
        "code": "df.set_index(pd.date_range(start='2024-01-01', periods=len(df)))"
    },
    {
        "task": "rolling calculations",
        "code": "df['tip'].rolling(window=3).mean()"
    },
    {
        "task": "expanding calculations",
        "code": "df['total_bill'].expanding().sum()"
    },

    # Data Merging and Joining
    {
        "task": "merge two dataframes on column",
        "code": "pd.merge(df1, df2, on='common_column')"
    },
    {
        "task": "join dataframes on index",
        "code": "df1.join(df2)"
    },
    {
        "task": "concatenate dataframes vertically",
        "code": "pd.concat([df1, df2], axis=0)"
    },
    {
        "task": "concatenate dataframes horizontally",
        "code": "pd.concat([df1, df2], axis=1)"
    },

    # String Operations
    {
        "task": "convert column to lowercase",
        "code": "df['column'].str.lower()"
    },
    {
        "task": "extract pattern from string",
        "code": "df['column'].str.extract(r'(pattern)')"
    },
    {
        "task": "split string column",
        "code": "df['column'].str.split(',', expand=True)"
    },

    # DateTime Operations
    {
        "task": "convert column to datetime",
        "code": "pd.to_datetime(df['date_column'])"
    },
    {
        "task": "extract year from date",
        "code": "df['date_column'].dt.year"
    },
    {
        "task": "calculate time difference",
        "code": "df['date_column'].diff().dt.days"
    },
    {
        "task": "calculate percentage of total",
        "code": "df['percentage'] = df['column'] / df['column'].sum() * 100"
    },
    {
        "task": "create bins from continuous data",
        "code": "df['bins'] = pd.qcut(df['column'], q=4, labels=['Q1', 'Q2', 'Q3', 'Q4'])"
    },
    {
        "task": "pivot and unstack data",
        "code": "df.pivot_table(values='value', index='row_category', columns='col_category', aggfunc='mean').unstack()"
    }
] 