SEABORN_EXAMPLES = [
    # Distribution Plots
    {
        "task": "create distribution plot of tips",
        "code": "sns.displot(data=df, x='tip', kind='hist')"
    },
    {
        "task": "show kernel density of bills",
        "code": "sns.kdeplot(data=df, x='total_bill', hue='Gender', fill=True)"
    },
    
    # Categorical Plots
    {
        "task": "create boxplot of tips by day",
        "code": "sns.boxplot(x='day', y='tip', data=df)"
    },
    {
        "task": "create violin plot with points",
        "code": "sns.violinplot(data=df, x='day', y='tip', inner='point')"
    },
    
    # Relational Plots
    {
        "task": "create scatter plot with regression line",
        "code": "sns.regplot(data=df, x='total_bill', y='tip')"
    },
    {
        "task": "create scatter plot with categorical splits",
        "code": "sns.lmplot(data=df, x='total_bill', y='tip', hue='Gender', col='day')"
    },
    
    # Matrix Plots
    {
        "task": "create correlation heatmap",
        "code": "sns.heatmap(df.corr(), annot=True, cmap='coolwarm')"
    },
    {
        "task": "create clustered heatmap",
        "code": "sns.clustermap(df.corr(), annot=True, cmap='vlag')"
    },
    
    # Advanced Plots
    {
        "task": "create pair plot with different variables",
        "code": "sns.pairplot(df, hue='Gender', vars=['total_bill', 'tip', 'size'])"
    },
    {
        "task": "create joint distribution plot",
        "code": "sns.jointplot(data=df, x='total_bill', y='tip', kind='hex')"
    },
    # Advanced Visualizations
    {
        "task": "create faceted scatter plot",
        "code": "sns.lmplot(data=df, x='total_bill', y='tip', col='time', row='day', hue='Gender')"
    },
    {
        "task": "plot categorical point plot",
        "code": "sns.pointplot(data=df, x='day', y='tip', hue='time', capsize=.1)"
    },
    {
        "task": "create complex violin plot",
        "code": "sns.violinplot(data=df, x='day', y='tip', hue='Gender', split=True)"
    },
    {
        "task": "plot distribution with rug plot",
        "code": "sns.displot(data=df, x='tip', kind='kde', rug=True)"
    },
    # Style Customization
    {
        "task": "set custom color palette",
        "code": "sns.set_palette('husl')\nsns.scatterplot(data=df, x='total_bill', y='tip')"
    },
    {
        "task": "customize plot style",
        "code": "sns.set_style('whitegrid')\nsns.set_context('talk')\nsns.boxplot(data=df, x='day', y='tip')"
    },
    {
        "task": "create custom figure size plot",
        "code": "plt.figure(figsize=(12, 6))\nsns.violinplot(data=df, x='day', y='tip')"
    },

    # Complex Visualizations
    {
        "task": "create multi-panel categorical plot",
        "code": "g = sns.catplot(data=df, x='day', y='tip', col='time', row='smoker', kind='box', height=4)"
    },
    {
        "task": "plot joint distribution with marginals",
        "code": "sns.jointplot(data=df, x='total_bill', y='tip', hue='Gender', kind='scatter', marginal_kws=dict(bins=25))"
    },
    {
        "task": "create residual plot",
        "code": "sns.residplot(data=df, x='total_bill', y='tip', lowess=True)"
    },
    {
        "task": "show tip distribution by time",
        "code": "sns.violinplot(x='time', y='tip', data=df)"
    },
    {
        "task": "create advanced facet grid",
        "code": "g = sns.FacetGrid(df, col='day', row='time', hue='Gender', height=4)\ng.map_dataframe(sns.scatterplot, x='total_bill', y='tip')\ng.add_legend()"
    },
    {
        "task": "create complex categorical plot",
        "code": "sns.catplot(data=df, x='day', y='tip', col='time', kind='violin', inner='stick', split=True, hue='Gender', height=6)"
    },
    {
        "task": "create advanced joint distribution",
        "code": "g = sns.JointGrid(data=df, x='total_bill', y='tip', hue='Gender')\ng.plot_joint(sns.kdeplot, levels=5)\ng.plot_marginals(sns.histplot)\ng.add_legend()"
    }
] 
