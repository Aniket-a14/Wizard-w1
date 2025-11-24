MULTI_STEP_EXAMPLES = [
    {
        "task": "clean missing values and show summary",
        "code": "df = df.dropna()\nprint(df.describe())"
    },
    {
        "task": "calculate mean age and plot histogram",
        "code": "mean_age = df['Age'].mean()\nprint(f'Mean Age: {mean_age}')\nimport seaborn as sns\nsns.histplot(df['Age'])\nplt.show()"
    },
    {
        "task": "group by category and plot bar chart",
        "code": "grouped = df.groupby('Category')['Sales'].sum().reset_index()\nimport seaborn as sns\nsns.barplot(data=grouped, x='Category', y='Sales')\nplt.show()"
    },
    {
        "task": "filter data and show first 5 rows",
        "code": "filtered_df = df[df['Score'] > 50]\nprint(filtered_df.head())"
    },
    {
        "task": "create new column and show correlation",
        "code": "df['Total'] = df['Quantity'] * df['Price']\nprint(df[['Total', 'Score']].corr())"
    }
]
