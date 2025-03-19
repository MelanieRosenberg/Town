import os
import json
import pandas as pd
from openai import OpenAI
import re
from dotenv import load_dotenv
from collections import Counter
from evaluate_classifications import evaluate_zero_deductible_accuracy

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
        "input_file": os.path.join(company_inputs, f"Company {company_id}.xlsx"),
        "expenses_file": os.path.join(company_intermediates, "expenses_to_classify.json"),
        "vendors_file": os.path.join(company_intermediates, "unique_vendors.json"),
        "classified_vendors_file": os.path.join(company_outputs, "classified_vendors.json"),
        "classified_expenses_file": os.path.join(company_outputs, "classified_expenses.json")
    }

class VendorClassifier:
    def __init__(self, company_id):
        self.company_id = company_id
        
        # Load config
        with open("config.json", "r") as f:
            config = json.load(f)
        self.company_config = config["companies"][company_id]
        
        self.paths = get_company_paths(company_id)
        
        # Ensure output directory exists
        os.makedirs(self.paths["outputs"], exist_ok=True)
        
        # Load expenses and vendors from JSON files
        with open(self.paths["expenses_file"], 'r') as f:
            self.expenses = json.load(f)
        with open(self.paths["vendors_file"], 'r') as f:
            self.vendors = json.load(f)
        
        # Initialize results
        self.classified_vendors = []
        self.classified_expenses = []
        
        # Get primary city from config
        self.primary_city = self.company_config["primary_city"]
        print(f"\nPrimary business location: {self.primary_city}\n")

    def get_gpt_classification(self, vendor_name, descriptions):
        """Use GPT to classify a vendor based on name and descriptions."""
        improved_prompt = f"""Classify this vendor for tax deduction purposes by researching the business type:

Vendor: {vendor_name}
Location: {self.primary_city}
Transaction Details: {descriptions if descriptions else 'None provided'}

RESEARCH PROCESS:
1. First, analyze the vendor name itself for clear indicators (restaurant, bar, cafe, etc.)
2. If unclear, conduct targeted research on "{vendor_name} {self.primary_city}" to determine business type
3. For businesses like "Blank Street" in New York, research would reveal it's a coffee shop chain
4. If vendor is "Unknown" or generic, carefully analyze the transaction description for clues

TAX CATEGORIES:
- ENTERTAINMENT (0%): Bars, clubs, venues, recreational activities, transportation
- MEALS (50%): Restaurants, cafes, coffee shops, food delivery, catering
- EMPLOYEE EVENTS (100%): Company-wide celebrations, holiday parties, team events for all employees

CRITICAL RULES:
1. Classify all bars and alcohol-focused venues as ENTERTAINMENT (0%)
2. Only classify as MEALS (50%) when food is clearly the primary offering
3. Only use EMPLOYEE EVENTS (100%) with explicit evidence in description (e.g., "team event", "team dinner")
4. When uncertain after research, default to ENTERTAINMENT (0%)
5. Key description terms like "dinner", "lunch", "meal" strongly suggest MEALS (50%)
6. Terms like "team dinner", "staff lunch" indicate EMPLOYEE EVENTS (100%)

Respond with ONLY this JSON:
{{
  "business_type": "Specific business type identified through research",
  "classification": "entertainment" or "meals" or "employee-events",
  "deduction_rate": 0.0 or 0.5 or 1.0,
  "reason": "Brief explanation including research findings",
  "confidence": "high" or "medium" or "low"
}}
"""
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a tax expert. Follow the research process exactly and apply the critical rules strictly. Default to entertainment (0%) when uncertain."},
                    {"role": "user", "content": improved_prompt}
                ],
                temperature=0
            )
            
            # Print raw response for debugging
            raw_response = response.choices[0].message.content
            try:
                # Try to find JSON in the response
                json_start = raw_response.find('{')
                json_end = raw_response.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = raw_response[json_start:json_end]
                    result = json.loads(json_str)
                    # Ensure deduction_rate is a number
                    if isinstance(result["deduction_rate"], str):
                        if "0" in result["deduction_rate"]:
                            result["deduction_rate"] = 0.0
                        elif "50" in result["deduction_rate"] or "0.5" in result["deduction_rate"]:
                            result["deduction_rate"] = 0.5
                        elif "100" in result["deduction_rate"] or "1" in result["deduction_rate"]:
                            result["deduction_rate"] = 1.0
                        else:
                            result["deduction_rate"] = 0.0  # Default to 0 if unclear
                else:
                    print(f"No JSON found in response for {vendor_name}")
                    raise json.JSONDecodeError("No JSON found", raw_response, 0)
            except json.JSONDecodeError as e:
                print(f"Failed to parse GPT response for {vendor_name}:")
                print(f"Raw response: {raw_response}")
                print(f"Parse error: {e}")
                raise
            
            result["vendor_name"] = vendor_name
            return result
            
        except Exception as e:
            print(f"Error classifying {vendor_name}: {e}")
            return {
                "vendor_name": vendor_name,
                "business_type": "unknown",
                "deduction_rate": 0.0,  # Default to 0% deductible to be conservative
                "classification": "entertainment",
                "reason": "Default conservative classification due to GPT error",
                "confidence": "low"
            }

    def classify_vendor(self, vendor_data):
        """Classify a vendor based on their transaction data."""
        vendor_name = str(vendor_data["vendor_name"])
        # Take at most 3 sample descriptions
        descriptions = vendor_data["sample_descriptions"][:3]
        
        # Use GPT for classification
        return self.get_gpt_classification(vendor_name, descriptions)

    def classify_all(self):
        # Process each vendor
        for i, vendor in enumerate(self.vendors):
            vendor_name = str(vendor["vendor_name"])
            print(f"\nProcessing vendor {i+1}/{len(self.vendors)}: {vendor_name}")
            print(f"Sample descriptions: {vendor['sample_descriptions'][:3]}")
            
            # For unknown vendors, use the expense_id to keep them unique
            if vendor_name.lower() == "unknown vendor":
                expense_id = vendor.get("expense_id")
                vendor_key = f"{vendor_name} (ID: {expense_id})"
                classified_vendor = self.classify_vendor(vendor)
                classified_vendor["vendor_name"] = vendor_key
                classified_vendor["expense_id"] = expense_id
                self.classified_vendors.append(classified_vendor)
                
                # For unknown vendors, match using expense_id
                vendor_expenses = [
                    e for e in self.expenses 
                    if e["expense_id"] == vendor["expense_id"]
                ]
            else:
                # Keep original behavior for known vendors
                vendor_key = vendor_name
                classified_vendor = self.classify_vendor(vendor)
                classified_vendor["vendor_name"] = vendor_key
                self.classified_vendors.append(classified_vendor)
                vendor_expenses = [e for e in self.expenses if e["Name"] == vendor_name]
            
            print(f"Classification: {classified_vendor['classification']}")
            print(f"Deduction rate: {classified_vendor['deduction_rate']}")
            print(f"Confidence: {classified_vendor.get('confidence', 'high')}")
            print(f"Reason: {classified_vendor['reason']}")
            
            total_amount = abs(sum(float(e["Amount"]) for e in vendor_expenses))
            deductible_amount = abs(total_amount * classified_vendor["deduction_rate"])
            print(f"Total expenses: ${total_amount:.2f}")
            print(f"Deductible amount: ${deductible_amount:.2f}")
            
            for expense in vendor_expenses:
                classified_expense = {
                    "date": expense["Date"],
                    "vendor": vendor_key,
                    "amount": abs(float(expense["Amount"])),
                    "description": expense["Memo/Description"],
                    "deduction_rate": classified_vendor["deduction_rate"],
                    "deductible_amount": abs(float(expense["Amount"])) * classified_vendor["deduction_rate"]
                }
                # Only add expense_id for unknown vendors
                if vendor_name.lower() == "unknown vendor":
                    classified_expense["expense_id"] = expense["expense_id"]
                self.classified_expenses.append(classified_expense)
        
        # Save results to JSON
        with open(self.paths["classified_vendors_file"], 'w') as f:
            json.dump(self.classified_vendors, f, indent=2)
            
        with open(self.paths["classified_expenses_file"], 'w') as f:
            json.dump(self.classified_expenses, f, indent=2)
        
        # Create vendor lists by deduction rate
        vendors_by_rate = {
            "0.0": [v["vendor_name"] for v in self.classified_vendors if v["deduction_rate"] == 0.0],
            "0.5": [v["vendor_name"] for v in self.classified_vendors if v["deduction_rate"] == 0.5],
            "1.0": [v["vendor_name"] for v in self.classified_vendors if v["deduction_rate"] == 1.0]
        }
        
        # Save vendor lists to separate JSON files
        for rate, vendors in vendors_by_rate.items():
            filename = f"vendors_deductible_{int(float(rate) * 100)}.json"
            filepath = os.path.join(self.paths["outputs"], filename)
            with open(filepath, 'w') as f:
                json.dump(vendors, f, indent=2)
        
        # Generate summary statistics
        summary = {
            "0.0": {
                "transactions": len([e for e in self.classified_expenses if e["deduction_rate"] == 0.0]),
                "vendors": len([v for v in self.classified_vendors if v["deduction_rate"] == 0.0]),
                "expenses": sum(e["amount"] for e in self.classified_expenses if e["deduction_rate"] == 0.0),
                "deductions": 0.0  # Always 0 for 0% group
            },
            "0.5": {
                "transactions": len([e for e in self.classified_expenses if e["deduction_rate"] == 0.5]),
                "vendors": len([v for v in self.classified_vendors if v["deduction_rate"] == 0.5]),
                "expenses": sum(e["amount"] for e in self.classified_expenses if e["deduction_rate"] == 0.5),
                "deductions": sum(e["amount"] for e in self.classified_expenses if e["deduction_rate"] == 0.5) * 0.5
            },
            "1.0": {
                "transactions": len([e for e in self.classified_expenses if e["deduction_rate"] == 1.0]),
                "vendors": len([v for v in self.classified_vendors if v["deduction_rate"] == 1.0]),
                "expenses": sum(e["amount"] for e in self.classified_expenses if e["deduction_rate"] == 1.0),
                "deductions": sum(e["amount"] for e in self.classified_expenses if e["deduction_rate"] == 1.0)
            }
        }
        
        # Calculate totals
        totals = {
            "transactions": sum(group["transactions"] for group in summary.values()),
            "vendors": len(self.classified_vendors),
            "expenses": sum(group["expenses"] for group in summary.values()),
            "deductions": sum(group["deductions"] for group in summary.values())
        }
        
        # Save summary to CSV
        summary_file = os.path.join(self.paths["outputs"], "final_summary.csv")
        with open(summary_file, 'w') as f:
            # Write header
            f.write("Group,Transactions,Unique Vendors,Total Expenses,Total Deductions\n")
            
            # Write each deduction group
            f.write(f"deductible: 0%,{summary['0.0']['transactions']},{summary['0.0']['vendors']},${summary['0.0']['expenses']:,.2f},${summary['0.0']['deductions']:,.2f}\n")
            f.write(f"deductible: 50%,{summary['0.5']['transactions']},{summary['0.5']['vendors']},${summary['0.5']['expenses']:,.2f},${summary['0.5']['deductions']:,.2f}\n")
            f.write(f"deductible: 100%,{summary['1.0']['transactions']},{summary['1.0']['vendors']},${summary['1.0']['expenses']:,.2f},${summary['1.0']['deductions']:,.2f}\n")
            
            # Write totals
            f.write(f"total,{totals['transactions']},{totals['vendors']},${totals['expenses']:,.2f},${totals['deductions']:,.2f}\n")
            
        print(f"\nClassification complete!")
        print(f"- Classified {len(self.classified_vendors)} vendors")
        print(f"- Processed {len(self.classified_expenses)} expenses")
        print("\nResults saved to:")
        print(f"- {self.paths['classified_vendors_file']}")
        print(f"- {self.paths['classified_expenses_file']}")
        print(f"- {summary_file}")

def classify_all(company_id):
    """Classify all vendors for a specific company."""
    # Load config
    with open("config.json", "r") as f:
        config = json.load(f)
    
    company_config = config["companies"][company_id]
    classifier = VendorClassifier(company_id)
    classifier.classify_all()

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Error: Company ID is required")
        print("Usage: python3 classify_vendors.py <company_id>")
        sys.exit(1)
    
    company_id = sys.argv[1]
    classify_all(company_id) 