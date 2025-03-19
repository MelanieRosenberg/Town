import pandas as pd
import json
import os
import sys

# Constants for directory structure
DATA_DIR = "data"
INPUTS_DIR = os.path.join(DATA_DIR, "inputs")
INTERMEDIATES_DIR = os.path.join(DATA_DIR, "intermediates")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")

def prepare_vendors(company_id):
    """Extract and prepare unique vendor data for a specific company."""
    # Load config
    with open("config.json", "r") as f:
        config = json.load(f)
    
    company_config = config["companies"][company_id]
    
    # Set up company-specific paths
    company_inputs = os.path.join(INPUTS_DIR, f"company{company_id}")
    company_intermediates = os.path.join(INTERMEDIATES_DIR, f"company{company_id}")
    company_outputs = os.path.join(OUTPUTS_DIR, f"company{company_id}")
    
    # Ensure directories exist
    os.makedirs(company_intermediates, exist_ok=True)
    os.makedirs(company_outputs, exist_ok=True)
    
    # Define file paths
    input_file = os.path.join(company_inputs, f"Company {company_id}.xlsx")
    expenses_file = os.path.join(company_intermediates, "expenses_to_classify.json")
    vendors_file = os.path.join(company_intermediates, "unique_vendors.json")
    
    # Read the Excel file with configured column names
    df = pd.read_excel(
        input_file,
        skiprows=3,
        names=company_config["column_names"]
    )
    
    # Convert Date column to string format
    df['Date'] = df['Date'].astype(str)
    
    # Print DataFrame info for debugging
    print(f"\nProcessing Company {company_id}")
    print("\nDataFrame columns:")
    print(df.columns.tolist())
    print("\nFirst few rows:")
    print(df.head())
    
    # Add an expense_id column (1-based index)
    df['expense_id'] = range(1, len(df) + 1)
    
    # Show counts for different M&E categories
    filter_column = company_config["filter"]["column"]
    filter_values = company_config["filter"]["values"]
    
    print(f"\nUnique values in {filter_column}:")
    print(df[filter_column].value_counts())
    
    # Apply filters
    filter_mask = df[filter_column].str.contains('|'.join(filter_values), na=False)
    df = df[filter_mask]
    print(f"\nTotal filtered expenses:", len(df))
    
    # Filter for specific expenses
    expenses_df = df[
        (df["Transaction Type"] == "Expense")
    ].copy()
    
    # Define columns to keep
    columns = [
        "Date",
        "Transaction Type",
        "Num",
        "Name",
        "Memo/Description",
        "Split",
        "Amount",
        "expense_id"
    ]
    
    # Keep only relevant columns
    expenses_df = expenses_df[columns]
    
    # Convert to list of dictionaries and save expenses
    expenses = expenses_df.to_dict('records')
    with open(expenses_file, 'w') as f:
        json.dump(expenses, f, indent=2)
    
    # Create unique vendors list
    vendors = []
    for expense in expenses:
        vendor_name = str(expense.get("Name", "")).strip()
        description = str(expense.get("Memo/Description", "")).strip()
        
        # If vendor is unknown/blank/nan, create a separate entry
        if pd.isna(vendor_name) or vendor_name.lower() in ['', 'unknown vendor', 'nan', 'none']:
            vendors.append({
                "vendor_name": "Unknown Vendor",
                "expense_id": expense['expense_id'],
                "sample_descriptions": [description] if description else []
            })
        else:
            # For known vendors, keep original behavior
            existing_vendor = next((v for v in vendors if v.get("vendor_name") == vendor_name), None)
            if existing_vendor:
                if description and description not in existing_vendor["sample_descriptions"]:
                    existing_vendor["sample_descriptions"].append(description)
            else:
                vendors.append({
                    "vendor_name": vendor_name,
                    "sample_descriptions": [description] if description else []
                })
    
    # Save unique vendors
    with open(vendors_file, 'w') as f:
        json.dump(vendors, f, indent=2)
    
    print(f"\nProcessed Company {company_id}:")
    print(f"- Found {len(expenses)} expenses")
    print(f"- Found {len(vendors)} unique vendors")
    print(f"- Files saved to {company_intermediates}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Error: Company ID is required")
        print("Usage: python3 prepare_vendors.py <company_id>")
        sys.exit(1)
    
    company_id = sys.argv[1]
    prepare_vendors(company_id) 