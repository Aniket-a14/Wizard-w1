NUMPY_EXAMPLES = [
    # Basic Array Operations
    {
        "task": "create array from list of tips",
        "code": "np.array(df['tip'].tolist())"
    },
    {
        "task": "create array of zeros",
        "code": "np.zeros(len(df))"
    },
    {
        "task": "create array of ones",
        "code": "np.ones(len(df))"
    },
    {
        "task": "create array with range",
        "code": "np.arange(len(df))"
    },
    {
        "task": "create linspace array",
        "code": "np.linspace(0, max(df['total_bill']), 50)"
    },

    # Array Manipulation
    {
        "task": "reshape tips into 2D array",
        "code": "np.array(df['tip']).reshape(-1, 2)"
    },
    {
        "task": "flatten 2D array to 1D",
        "code": "np.array([df['tip'], df['total_bill']]).flatten()"
    },
    {
        "task": "transpose array",
        "code": "np.array([df['tip'], df['total_bill']]).T"
    },
    {
        "task": "stack arrays vertically",
        "code": "np.vstack((df['tip'], df['total_bill']))"
    },
    {
        "task": "stack arrays horizontally",
        "code": "np.hstack((df['tip'].values.reshape(-1,1), df['total_bill'].values.reshape(-1,1)))"
    },

    # Mathematical Operations
    {
        "task": "add constant to all tips",
        "code": "np.add(df['tip'], 5)"
    },
    {
        "task": "multiply tips by scalar",
        "code": "np.multiply(df['tip'], 2)"
    },
    {
        "task": "divide bills by constant",
        "code": "np.divide(df['total_bill'], 100)"
    },
    {
        "task": "calculate power of tips",
        "code": "np.power(df['tip'], 2)"
    },
    {
        "task": "calculate square root of bills",
        "code": "np.sqrt(df['total_bill'])"
    },

    # Statistical Functions
    {
        "task": "calculate mean of tips",
        "code": "np.mean(df['tip'])"
    },
    {
        "task": "find median of bills",
        "code": "np.median(df['total_bill'])"
    },
    {
        "task": "compute standard deviation",
        "code": "np.std(df['tip'])"
    },
    {
        "task": "calculate variance",
        "code": "np.var(df['total_bill'])"
    },
    {
        "task": "find minimum value",
        "code": "np.min(df['tip'])"
    },

    # Advanced Math
    {
        "task": "calculate logarithm of bills",
        "code": "np.log(df['total_bill'])"
    },
    {
        "task": "compute exponential",
        "code": "np.exp(df['tip'])"
    },
    {
        "task": "calculate sine",
        "code": "np.sin(df['total_bill'])"
    },
    {
        "task": "find cosine",
        "code": "np.cos(df['tip'])"
    },
    {
        "task": "compute tangent",
        "code": "np.tan(df['total_bill'])"
    },

    # Array Comparison
    {
        "task": "find tips greater than 5",
        "code": "np.where(df['tip'] > 5)"
    },
    {
        "task": "check if any tips above 20",
        "code": "np.any(df['tip'] > 20)"
    },
    {
        "task": "check if all bills positive",
        "code": "np.all(df['total_bill'] > 0)"
    },
    {
        "task": "find tips between values",
        "code": "np.where((df['tip'] >= 5) & (df['tip'] <= 10))"
    },
    {
        "task": "compare tips and bills",
        "code": "np.greater(df['tip'], df['total_bill'])"
    }
] 