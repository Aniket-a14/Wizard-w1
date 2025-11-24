MATPLOTLIB_EXAMPLES = [
    # Basic Plots
    {
        "task": "create histogram of total_bill",
        "code": "plt.hist(df['total_bill'], bins=20)\nplt.title('Distribution of Bills')\nplt.xlabel('Bill Amount')\nplt.show()"
    },
    {
        "task": "create scatter plot of bill vs tip",
        "code": "plt.scatter(df['total_bill'], df['tip'])\nplt.xlabel('Total Bill')\nplt.ylabel('Tip')\nplt.show()"
    },
    
    # Line Plots
    {
        "task": "plot tips over time",
        "code": "plt.plot(df.index, df['tip'], 'b-')\nplt.title('Tips Over Time')\nplt.show()"
    },
    {
        "task": "create multiple line plot",
        "code": "plt.plot(df['total_bill'], label='Bills')\nplt.plot(df['tip'], label='Tips')\nplt.legend()\nplt.show()"
    },
    
    # Bar Charts
    {
        "task": "create bar plot of average tips by day",
        "code": "df.groupby('day')['tip'].mean().plot(kind='bar')\nplt.title('Average Tips by Day')\nplt.show()"
    },
    {
        "task": "create horizontal bar chart",
        "code": "df.groupby('day')['tip'].sum().plot(kind='barh')\nplt.title('Total Tips by Day')\nplt.show()"
    },
    
    # Advanced Plots
    {
        "task": "create subplot with histogram and boxplot",
        "code": "fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))\nax1.hist(df['tip'])\nax1.set_title('Tip Distribution')\nax2.boxplot(df['tip'])\nax2.set_title('Tip Box Plot')\nplt.tight_layout()\nplt.show()"
    },
    {
        "task": "create pie chart of customer distribution",
        "code": "plt.pie(df['day'].value_counts(), labels=df['day'].unique(), autopct='%1.1f%%')\nplt.title('Customer Distribution by Day')\nplt.show()"
    },
    
    # Customization
    {
        "task": "create plot with grid and custom style",
        "code": "plt.style.use('seaborn')\nplt.plot(df['tip'])\nplt.grid(True, linestyle='--', alpha=0.7)\nplt.show()"
    },
    {
        "task": "create plot with custom colors and markers",
        "code": "plt.plot(df['tip'], 'ro-', linewidth=2, markersize=8)\nplt.show()"
    },
    {
        "task": "create stacked bar chart",
        "code": "df.groupby(['day', 'Gender'])['tip'].mean().unstack().plot(kind='bar', stacked=True)"
    },
    {
        "task": "plot with secondary y-axis",
        "code": "fig, ax1 = plt.subplots()\nax2 = ax1.twinx()\nax1.plot(df['tip'], 'g-')\nax2.plot(df['total_bill'], 'b-')"
    },
    {
        "task": "create annotated heatmap",
        "code": "plt.imshow(df.corr())\nfor i in range(len(df.columns)):\n    for j in range(len(df.columns)):\n        plt.text(j, i, f\"{df.corr().iloc[i, j]:.2f}\", ha='center', va='center')"
    },
    {
        "task": "create histogram of tips",
        "code": "plt.hist(df['tip'])\nplt.title('Distribution of Tips')\nplt.xlabel('Tip Amount')\nplt.ylabel('Frequency')"
    },
    {
        "task": "plot total_bill vs tip scatter",
        "code": "plt.scatter(df['total_bill'], df['tip'])\nplt.xlabel('Total Bill')\nplt.ylabel('Tip')"
    },
    {
        "task": "create multiple subplots",
        "code": "fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))\nax1.hist(df['column1'])\nax2.hist(df['column2'])\nplt.show()"
    },
    {
        "task": "create box plot with grid",
        "code": "plt.boxplot(df['column'])\nplt.grid(True, linestyle='--', alpha=0.7)\nplt.show()"
    },
    {
        "task": "create plot with custom markers and colors",
        "code": "plt.plot(df['x'], df['y'], 'ro--', linewidth=2, markersize=10)\nplt.show()"
    }
] 