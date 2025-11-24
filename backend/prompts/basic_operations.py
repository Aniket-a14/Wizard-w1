BASIC_EXAMPLES = [
    # Viewing Data
    {
        "task": "show first 5 rows",
        "code": "df.head(5)"
    },
    {
        "task": "show last 5 rows",
        "code": "df.tail(5)"
    },
    {
        "task": "display last 5 rows",
        "code": "df.tail(5)"
    },
    {
        "task": "show basic information",
        "code": "df.info()"
    },
    {
        "task": "show column names",
        "code": "df.columns"
    },
    {
        "task": "show data types of columns",
        "code": "df.dtypes"
    },
    {
        "task": "show shape of dataset",
        "code": "df.shape"
    },
    {
        "task": "show index of dataframe",
        "code": "df.index"
    },
    {
        "task": "check for missing values",
        "code": "df.isnull().sum()"
    },
    {
        "task": "show memory usage",
        "code": "df.memory_usage(deep=True)"
    },
    # Full Dataset Display
    {
        "task": "show the full dataset",
        "code": "df"
    },
    {
        "task": "display all rows without truncation",
        "code": "pd.set_option('display.max_rows', None)\ndf"
    },
    {
        "task": "show all columns without truncation",
        "code": "pd.set_option('display.max_columns', None)\ndf"
    },
    {
        "task": "display dataset as string",
        "code": "df.to_string()"
    },
    {
        "task": "reset index and show all data",
        "code": "df.reset_index(drop=True)"
    },
    # Standalone Operations (No Dataset Required)
    {
        "task": "calculate square root of 16",
        "code": "np.sqrt(16)"
    },
    {
        "task": "calculate power of 2 to 3",
        "code": "2 ** 3"
    },
    {
        "task": "calculate mean of numbers 1,2,3,4,5",
        "code": "np.mean([1, 2, 3, 4, 5])"
    },
    {
        "task": "create a list of numbers from 1 to 10",
        "code": "list(range(1, 11))"
    },
    {
        "task": "create numpy array of zeros with size 5",
        "code": "np.zeros(5)"
    },
    {
        "task": "create numpy array of ones with shape 2x3",
        "code": "np.ones((2, 3))"
    },
    {
        "task": "generate random number between 0 and 1",
        "code": "np.random.random()"
    },
    {
        "task": "calculate sine of 90 degrees",
        "code": "np.sin(np.deg2rad(90))"
    },
    {
        "task": "round 3.14159 to 2 decimal places",
        "code": "round(3.14159, 2)"
    },
    {
        "task": "create a random matrix of size 3x3",
        "code": "np.random.rand(3, 3)"
    },
    # Filtering Data
    {
        "task": "show rows where gender is Male",
        "code": "df[df['Gender'] == 'Male']"
    },
    {
        "task": "show the rows which have gender Male",
        "code": "df[df['Gender'] == 'Male']"
    },
    {
        "task": "filter rows where gender is Female",
        "code": "df[df['Gender'] == 'Female']"
    },
    {
        "task": "show data for smokers only",
        "code": "df[df['smoker'] == 'Yes']"
    },
    {
        "task": "show data for dinner time",
        "code": "df[df['time'] == 'Dinner']"
    },
    {
        "task": "show data where total bill is greater than 20",
        "code": "df[df['total_bill'] > 20]"
    },
    {
        "task": "show data where tip is less than 3",
        "code": "df[df['tip'] < 3]"
    },
    {
        "task": "show data for weekend days",
        "code": "df[df['day'].isin(['Sat', 'Sun'])]"
    },
    {
        "task": "show unique values in a column",
        "code": "df['column'].unique()"
    },
    {
        "task": "count value frequencies",
        "code": "df['column'].value_counts()"
    },
    {
        "task": "show sample of 5 random rows",
        "code": "df.sample(5)"
    },
    {
        "task": "show percentage of missing values",
        "code": "df.isnull().mean() * 100"
    }
] 