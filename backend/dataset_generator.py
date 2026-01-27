import csv
import json
import random
import os
import sys

# Ensure we can import from backend if needed, though this script is standalone-ish
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configuration
OUTPUT_FILE = 'backend/dataset/instruction_code_dataset.csv'
KNOWLEDGE_BASE_FILE = 'backend/prompts/knowledge_base.json'
TARGET_ROWS = 500000  # Target size
BATCH_SIZE = 1000     # Flush to disk every N rows

# Domain Schemas (Dynamic Schema Engine)
DOMAINS = {
    "Retail": ["TransactionID", "CustomerID", "Product", "Category", "Price", "Quantity", "TotalAmount", "Date", "Region"],
    "Healthcare": ["PatientID", "Age", "Gender", "Diagnosis", "BloodPressure", "Cholesterol", "TreatmentCost", "VisitDate"],
    "Finance": ["AccountID", "TransactionDate", "Amount", "Type", "Balance", "Merchant", "FraudFlag", "CreditScore"],
    "RealEstate": ["PropertyID", "AreaSqFt", "Price", "Bedrooms", "Bathrooms", "Location", "YearBuilt", "Type"],
    "Education": ["StudentID", "Grade", "Subject", "Score", "Attendance", "Teacher", "Semester"],
    "Tech": ["UserID", "AppUsageTime", "DataConsumed", "DeviceType", "SubscriptionStatus", "SupportTickets"],
}

# Categorize columns for smart injection
COL_TYPES = {
    "num_col": ["Price", "Quantity", "TotalAmount", "Age", "BloodPressure", "Cholesterol", "TreatmentCost", "Amount", "Balance", "CreditScore", "AreaSqFt", "Bedrooms", "Bathrooms", "YearBuilt", "Score", "AppUsageTime", "DataConsumed", "SupportTickets"],
    "cat_col": ["Category", "Region", "Gender", "Diagnosis", "Type", "Merchant", "FraudFlag", "Location", "Subject", "Teacher", "DeviceType", "SubscriptionStatus"],
    "date_col": ["Date", "VisitDate", "TransactionDate"],
    "id_col": ["TransactionID", "CustomerID", "PatientID", "AccountID", "PropertyID", "StudentID", "UserID"]
}

def load_knowledge_base():
    with open(KNOWLEDGE_BASE_FILE, 'r') as f:
        return json.load(f)

def get_random_columns(domain, col_type=None, count=1):
    cols = DOMAINS[domain]
    if col_type:
        # Intersection of domain columns and type columns
        valid_cols = [c for c in cols if c in COL_TYPES.get(col_type, [])]
        if not valid_cols:
             return [random.choice(cols)] * count # Fallback
        return [random.choice(valid_cols) for _ in range(count)]
    return [random.choice(cols) for _ in range(count)]

def fill_template(template, domain):
    code = template['code']
    task = template['task']
    keywords = template.get('keywords', [])
    
    # Identify variables in the template (e.g., {col}, {x_col})
    # We will replace them with random columns from the chosen domain
    
    # Heuristic for replacement
    mappings = {}
    
    # Numerical columns
    num_cols = get_random_columns(domain, "num_col", 3)
    mappings['{num_col}'] = num_cols[0]
    mappings['{val_col}'] = num_cols[1]
    mappings['{y_col}'] = num_cols[0] # Usually Y is numerical
    mappings['{x_col}'] = num_cols[1] # X can be numerical
    mappings['{col}'] = num_cols[2]
    mappings['{col1}'] = num_cols[0]
    mappings['{col2}'] = num_cols[1]

    # Categorical columns
    cat_cols = get_random_columns(domain, "cat_col", 2)
    mappings['{cat_col}'] = cat_cols[0]
    mappings['{target_col}'] = cat_cols[0] # Classification target
    mappings['{x_col_2}'] = cat_cols[1] # Extra feature
    
    # Date columns
    date_cols = get_random_columns(domain, "date_col", 1)
    mappings['{date_col}'] = date_cols[0]

    # Values
    mappings['{val}'] = str(random.randint(10, 1000))
    mappings['{val1}'] = "GroupA"
    mappings['{val2}'] = "GroupB"
    mappings['{n}'] = str(random.randint(5, 20))
    
    # Apply replacements
    for key, val in mappings.items():
        code = code.replace(key, val)
        task = task.replace(key, val)
        
    # Extra cleanup if any braces remain (rare fallback)
    if '{' in code:
        pass # In a real system, we'd log this

    return {"instruction": task, "code": code}

def generate_dataset():
    print(f"Loading knowledge base from {KNOWLEDGE_BASE_FILE}...")
    try:
        kb = load_knowledge_base()
    except FileNotFoundError:
        print("Knowledge base not found!")
        return

    print(f"Generating {TARGET_ROWS} rows...")
    
    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['instruction', 'code'])
        writer.writeheader()
        
        count = 0
        while count < TARGET_ROWS:
            # Pick a random library
            lib = random.choice(list(kb['libraries'].keys()))
            templates = kb['libraries'][lib]
            
            # Pick a random template
            template = random.choice(templates)
            
            # Pick a random domain context
            domain = random.choice(list(DOMAINS.keys()))
            
            # Generate pair
            row = fill_template(template, domain)
            
            writer.writerow(row)
            count += 1
            
            if count % 10000 == 0:
                print(f"Generated {count} rows...")

    print(f"Successfully generated {TARGET_ROWS} rows in {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_dataset()
