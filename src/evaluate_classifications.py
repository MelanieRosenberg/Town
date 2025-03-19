import os
import json
import sys

# Constants for directory structure
DATA_DIR = "data"
INPUTS_DIR = os.path.join(DATA_DIR, "inputs")
INTERMEDIATES_DIR = os.path.join(DATA_DIR, "intermediates")
OUTPUTS_DIR = os.path.join(DATA_DIR, "outputs")

def get_company_paths(company_id):
    """Get all file paths for a specific company."""
    company_inputs = os.path.join(INPUTS_DIR, f"company{company_id}")
    company_intermediates = os.path.join(INTERMEDIATES_DIR, f"company{company_id}")
    company_outputs = os.path.join(OUTPUTS_DIR, f"company{company_id}")
    
    return {
        "inputs": company_inputs,
        "intermediates": company_intermediates,
        "outputs": company_outputs,
        "eval_set_file": os.path.join(company_intermediates, "zero_deductible_eval_set.json"),
        "classified_vendors_file": os.path.join(company_outputs, "classified_vendors.json")
    }

def evaluate_zero_deductible_accuracy(company_id):
    """Evaluate accuracy of zero deductible classifications against known evaluation set."""
    # Load config
    with open("config.json", "r") as f:
        config = json.load(f)
    
    company_config = config["companies"][company_id]
    
    # Check if evaluation is enabled for this company
    if not company_config.get("eval_set", True):
        print(f"\nEvaluation skipped for Company {company_id} (eval_set=False in config)")
        return
    
    # Define paths
    data_dir = "data"
    intermediates_dir = os.path.join(data_dir, "intermediates", f"company{company_id}")
    outputs_dir = os.path.join(data_dir, "outputs", f"company{company_id}")
    
    eval_set_file = os.path.join(intermediates_dir, "zero_deductible_eval_set.json")
    classified_vendors_file = os.path.join(outputs_dir, "classified_vendors.json")
    
    # Load evaluation set
    with open(eval_set_file, 'r') as f:
        eval_set = json.load(f)
        known_zero_deductible = set(eval_set["vendors"])
    
    # Load classified vendors
    with open(classified_vendors_file, 'r') as f:
        classified_vendors = json.load(f)
    
    # Check each known zero deductible vendor
    correct = 0
    incorrect = []
    total = len(known_zero_deductible)
    
    for vendor in classified_vendors:
        if vendor["vendor_name"] in known_zero_deductible:
            if vendor["deduction_rate"] == 0.0:
                correct += 1
            else:
                incorrect.append({
                    "vendor": vendor["vendor_name"],
                    "classified_rate": vendor["deduction_rate"],
                    "reason": vendor["reason"]
                })
    
    # Calculate accuracy
    accuracy = (correct / total) * 100 if total > 0 else 0
    
    # Print results
    print("\nZero Deductible Classification Evaluation:")
    print(f"Total known zero deductible vendors: {total}")
    print(f"Correctly classified as zero deductible: {correct}")
    print(f"Accuracy: {accuracy:.1f}%")
    
    if incorrect:
        print("\nIncorrectly classified vendors:")
        for vendor in incorrect:
            print(f"\nVendor: {vendor['vendor']}")
            print(f"Classified as: {vendor['classified_rate']*100}% deductible")
            print(f"Reason: {vendor['reason']}")
    
    return accuracy, incorrect

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Error: Company ID is required")
        print("Usage: python3 evaluate_classifications.py <company_id>")
        sys.exit(1)
    
    company_id = sys.argv[1]
    evaluate_zero_deductible_accuracy(company_id) 