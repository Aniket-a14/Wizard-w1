import csv
import random


n_values = [3, 5, 10, 15]
columns = ["Age", "Salary", "Experience", "Revenue", "Cost", "Profit", "Category", "Score"]
bins_values = [10, 15, 20, 25]

templates = [
    {
        "instruction_template": "Show the first {n} rows of the dataset.",
        "code_template": "print(df.head({n}))"
    },
    {
        "instruction_template": "Display the summary statistics of the dataset.",
        "code_template": "print(df.describe())"
    },
    {
        "instruction_template": "Plot a histogram of the '{col}' column with {bins} bins.",
        "code_template": "import seaborn as sns; sns.histplot(df['{col}'], bins={bins}); plt.show()"
    },
    {
        "instruction_template": "Plot a scatter plot with '{x_col}' on the x-axis and '{y_col}' on the y-axis.",
        "code_template": "import seaborn as sns; sns.scatterplot(x=df['{x_col}'], y=df['{y_col}']); plt.show()"
    },
    {
        "instruction_template": "Calculate the mean of the '{col}' column.",
        "code_template": "print(df['{col}'].mean())"
    },
    {
        "instruction_template": "Show all the columns of the dataset.",
        "code_template": "print(df.columns)"
    },
    {
        "instruction_template": "Plot a line chart of '{y_col}' over '{x_col}'.",
        "code_template": "import matplotlib.pyplot as plt; plt.plot(df['{x_col}'], df['{y_col}']); plt.show()"
    },
    {
        "instruction_template": "Check for missing values in the dataset.",
        "code_template": "print(df.isnull().sum())"
    },
    {
        "instruction_template": "Drop rows with missing values and display the new shape of the dataset.",
        "code_template": "df = df.dropna(); print('New shape:', df.shape)"
    },
    {
        "instruction_template": "Display the unique values in the '{col}' column.",
        "code_template": "print(df['{col}'].unique())"
    },
]

def fill_template(template):
    instruction = template["instruction_template"]
    code = template["code_template"]
    
    # Add validation for required template variables
    required_vars = {"{n}", "{col}", "{bins}", "{x_col}", "{y_col}"}
    template_vars = set(v for v in required_vars if v in instruction or v in code)
    
    # Store x_col for reuse in y_col selection
    x_col = None
    
    for var in template_vars:
        if var == "{n}":
            val = str(random.choice(n_values))
        elif var == "{col}":
            val = random.choice(columns)
        elif var == "{bins}":
            val = str(random.choice(bins_values))
        elif var == "{x_col}":
            x_col = random.choice(columns)
            val = x_col
        elif var == "{y_col}" and x_col:
            # Ensure y_col is different from x_col when possible
            val = random.choice([c for c in columns if c != x_col] or columns)
        else:
            val = random.choice(columns)
            
        instruction = instruction.replace(var, val)
        code = code.replace(var, val)
    
    return {"instruction": instruction, "code": code}

def generate_dataset(num_entries=1000, output_file='instruction_code_dataset.csv'):
    data = [fill_template(random.choice(templates)) for _ in range(num_entries)]
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['instruction', 'code']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for entry in data:
            writer.writerow(entry)
    
    print(f"Dataset with {num_entries} instruction-code pairs saved to '{output_file}'.")

if __name__ == "__main__":
    generate_dataset()


#this block of code is used to generate a dataset of instruction-code pairs
#the dataset is saved to a csv file
#the dataset is used in the agent.py file to train the agent



