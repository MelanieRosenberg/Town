import pandas as pd
import json
import os

# Constants for directory structure
DATA_DIR = "data"
INPUTS_DIR = os.path.join(DATA_DIR, "inputs")
INTERMEDIATES_DIR = os.path.join(DATA_DIR, "intermediates")

# Company specific directories
COMPANY_A_INPUTS = os.path.join(INPUTS_DIR, "companyA")
COMPANY_A_INTERMEDIATES = os.path.join(INTERMEDIATES_DIR, "companyA")

# Input/Output files
COMPANY_A_FILE = os.path.join(COMPANY_A_INPUTS, "Company A.xlsx")
EVAL_SET_FILE = os.path.join(COMPANY_A_INTERMEDIATES, "zero_deductible_eval_set.json")

def extract_zero_deductible_vendors():
    """Extract vendors that are known to be 0% deductible from Company A's eval set."""
    # Ensure directories exist
    os.makedirs(COMPANY_A_INTERMEDIATES, exist_ok=True)
    
    # Check if file exists
    if not os.path.exists(COMPANY_A_FILE):
        print(f"Please place 'Company A.xlsx' in {COMPANY_A_INPUTS}")
        return
    
    # Read the eval set from Excel file, skipping the first row
    df = pd.read_excel(COMPANY_A_FILE, sheet_name="Eval Set", header=0)
    
    # Skip empty rows
    vendors = df.dropna().iloc[:, 0]
    
    # Create list of vendor names
    vendor_list = []
    for vendor_name in vendors:
        vendor_name = str(vendor_name).strip()
        if not vendor_name or vendor_name.lower() == "vendor":  # Skip empty names and header
            continue
        vendor_list.append(vendor_name)
    
    # Create evaluation set format
    eval_set = {
        "vendors": vendor_list
    }
    
    # Save the evaluation set
    with open(EVAL_SET_FILE, "w") as f:
        json.dump(eval_set, f, indent=2)
    
    print(f"\nFound {len(vendor_list)} zero deductible vendors:")
    for vendor in vendor_list:
        print(f"- {vendor}")

if __name__ == "__main__":
    extract_zero_deductible_vendors() 