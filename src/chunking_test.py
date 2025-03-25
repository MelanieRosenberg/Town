import os
import json
import pandas as pd
import openai
import re
from dotenv import load_dotenv
from collections import Counter
from evaluate_classifications import evaluate_zero_deductible_accuracy
import itertools
from pydantic import BaseModel, Field
import argparse

# Load environment variables from .env file
load_dotenv()

# Initialize OpenAI client
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

def generate_prompt(model_type, chunks, primary_city):
    """
    Generate the appropriate prompt based on the classification type.
    
    Args:
        model_type: "vendors" or "expenses"
        chunks: list of chunks to classify
        primary_city: primary location for context
        
    Returns:
        string: Formatted prompt for API call
    """
    # Format data based on type
    if model_type == "vendors":
        data_label = "Vendors"
        data_list = [{"vendor": chunk.vendor_name, "description": chunk.description} for chunk in chunks]
    else:  # expenses
        data_label = "Expenses"
        data_list = [
            {
                "vendor": chunk.vendor_name,
                "description": chunk.description,
                "amount": chunk.amount,
                "date": chunk.date
            } for chunk in chunks
        ]
    
    # Common tax category information and rules
    common_text = """
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
    """
    
    # Create unified prompt
    prompt = f"""Classify these {model_type} for tax deduction purposes:
    {data_label}: {json.dumps(data_list, indent=2)}
    Location: {primary_city}

    RESEARCH PROCESS:
    1. Analyze each vendor name for clear indicators (restaurant, bar, cafe, etc.)
    2. If unclear, conduct targeted research on the vendor name in {primary_city}
    3. For businesses like "Blank Street" in New York, research would reveal it's a coffee shop chain
    4. If vendor is "Unknown", carefully analyze the transaction description for clues
    {common_text}
    7. IMPORTANT: Return one classification object for EACH {model_type[:-1]} in the input list

    Respond with ONLY this JSON array containing exactly {len(chunks)} items:
    [
      {{
        "vendor_name": "vendor name",
        "business_type": "Specific business type identified",
        "classification": "entertainment" or "meals" or "employee-events",
        "deduction_rate": 0.0 or 0.5 or 1.0,
        "reason": "Brief explanation including research findings",
        "confidence": "high" or "medium" or "low"
      }},
      ...
    ]
    """
    
    return prompt
    
class ExpenseChunk(BaseModel):
    vendor_name: str = Field(description="Name of the vendor")
    description: str = Field(description="Transaction description/memo")
    amount: float = Field(description="Transaction amount")
    date: str = Field(description="Transaction date")


class ExpenseClassifier:
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

        print(f"Loaded {len(self.expenses)} expenses")

        with open(self.paths["vendors_file"], 'r') as f:
            self.vendors = json.load(f)

        print(f"Loaded {len(self.vendors)} vendors")

        # Get primary city from config
        self.primary_city = self.company_config["primary_city"]
        print(f"Primary business location: {self.primary_city}")


    def get_classification(self, model_type, chunks):
        """
        Get classification from GPT for the given chunks.

        Args:
            model_type: str - "vendors" or "expenses"
            chunks: list[ExpenseChunk] - list of chunks to classify
            
        Returns:
            list - Classifications as dictionaries
        """
        try:
            # Generate prompt for the batch
            prompt = generate_prompt(model_type, chunks, self.primary_city)
            
            print(f"Requesting classification for {len(chunks)} {model_type}...")
            
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", 
                        "content": "You are a tax expert. Follow the research process exactly and apply the critical rules strictly. Default to entertainment (0%) when uncertain."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0
            )
            
            raw_response = response.choices[0].message.content
            
            try:
                # Clean and parse the response
                cleaned_response = raw_response.replace('```json', '').replace('```', '').strip()
                parsed_result = json.loads(cleaned_response)
                
                # Ensure we have a list for consistent handling
                if not isinstance(parsed_result, list):
                    parsed_result = [parsed_result]
                
                # Make sure we have the right number of results
                if len(parsed_result) < len(chunks):
                    print(f"Warning: Got {len(parsed_result)} results but expected {len(chunks)}. Adding default classifications.")
                    for i in range(len(parsed_result), len(chunks)):
                        parsed_result.append(self._get_default_classification(chunks[i].vendor_name))
                
                # Process each result
                for i, result in enumerate(parsed_result):
                    if i < len(chunks):
                        # Normalize deduction rate
                        if isinstance(result.get("deduction_rate"), str):
                            result["deduction_rate"] = float(result["deduction_rate"].replace("%", "")) / 100
                        
                        # Add date from the original chunk for expenses
                        if model_type == "expenses" and chunks[i].date:
                            result["date"] = chunks[i].date.split()[0] if chunks[i].date else ""
                
                return parsed_result
                
            except json.JSONDecodeError as e:
                print(f"Failed to parse response:")
                print(f"Response: {raw_response}")
                print(f"Error: {e}")
                # Use default classifications as fallback
                return [self._get_default_classification(chunk.vendor_name) for chunk in chunks]
            
        except Exception as e:
            print(f"Error during classification: {e}")
            return [self._get_default_classification(chunk.vendor_name) for chunk in chunks]

    def _get_default_classification(self, vendor_name):
        """Return default conservative classification."""
        return {
            "vendor_name": vendor_name,
            "business_type": "unknown",
            "deduction_rate": 0.0,
            "classification": "entertainment",
            "reason": "Default conservative classification due to error",
            "confidence": "low"
        }

    def run_classification(self, model_type="expenses", batch_size=2):
        """
        Main method to run the classification process.
        Args:
            model_type: str - "vendors" or "expenses"
            batch_size: int - number of items per batch (for expenses only, vendors are processed one at a time)
        """
        print(f"\nStarting {model_type} classification...")
        
        # Determine what we're processing
        items_to_process = self.vendors if model_type == "vendors" else self.expenses
        total_items = len(items_to_process)
        
        if total_items == 0:
            print(f"No {model_type} to process.")
            return []
        
        print(f"Processing {total_items} {model_type}...")
        
        classified_items = []
        batch_count = 0
        
        # Process in batches
        for i in range(0, total_items, batch_size):
            batch = items_to_process[i:i+batch_size]
            batch_count += 1
            
            print(f"\nProcessing batch {batch_count} of {(total_items + batch_size - 1) // batch_size}...")
            
            # Prepare chunks for processing
            chunks = []
            for item in batch:
                try:
                    if model_type == "vendors":
                        # Handle vendor format
                        vendor_name = item.get("vendor_name", "Unknown")
                        descriptions = item.get("sample_descriptions", [])
                        description = descriptions[0] if descriptions else "No description available"
                        amount = 0.0  # Vendors don't have amounts
                        date = ""     # Vendors don't have dates
                        
                        print(f"Processing vendor: {vendor_name} with {len(descriptions)} sample descriptions")
                    else:
                        # Handle expense format
                        vendor_name = item.get("Name", "Unknown")
                        description = item.get("Memo/Description", "No description available")
                        amount = float(item.get("Amount", 0.0)) if pd.notna(item.get("Amount")) else 0.0
                        date = str(item.get("Date", "")) if pd.notna(item.get("Date")) else ""
                        
                        formatted_date = date.split()[0] if date else ""
                        print(f"Processing expense: {formatted_date}, vendor: {vendor_name}, ${abs(amount):.2f}")
                    
                    # Handle NaN values
                    if pd.isna(vendor_name): vendor_name = "Unknown"
                    if pd.isna(description): description = "No description available"
                    
                    # Create a standardized chunk
                    chunk = ExpenseChunk(
                        vendor_name=vendor_name,
                        description=description,
                        amount=amount,
                        date=date
                    )
                    chunks.append(chunk)
                except Exception as e:
                    print(f"Error processing {model_type[:-1]}: {item}")
                    print(f"Error details: {e}")
                    continue
            
            if chunks:
                # Get classifications for the batch
                result = self.get_classification(model_type, chunks)
                classified_items.extend(result)
                
                # Log the results
                for item in result:
                    if model_type == "expenses":
                        print(f"{item.get('date', '')}, vendor: {item['vendor_name']}: {item['classification']} ({item['deduction_rate']*100}%)")
                    else:
                        print(f"vendor: {item['vendor_name']}: {item['classification']} ({item['deduction_rate']*100}%)")
        
        # Save the results
        output_file = self.paths[f"classified_{model_type}_file"]
        print(f"\nSaving results to {output_file}")
        with open(output_file, 'w') as f:
            json.dump(classified_items, f, indent=2)
        
        print(f"Classification complete. Processed {len(classified_items)} {model_type}")
        
        return classified_items
    
    def process_vendors(self, batch_size):
        """
        Specialized method to process vendors with appropriate handling for vendor data structure.
        
        Args:
            batch_size: int - number of vendors to process per batch
        
        Returns:
            list - Classified vendors
        """
        
        return self.run_classification(model_type="vendors", batch_size=batch_size)
    
    def process_expenses(self, batch_size):
        """
        Specialized method to process expenses with appropriate handling for expense data structure.
        
        Args:
            batch_size: int - number of expenses to process per batch
        
        Returns:
            list - Classified expenses
        """
        return self.run_classification(model_type="expenses", batch_size=batch_size)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Classify expenses or vendors for tax purposes')
    parser.add_argument('company_id', help='Company ID to process')
    parser.add_argument('--type', choices=['expenses', 'vendors'], default='expenses',
                      help='Type of classification to run (default: expenses)')
    parser.add_argument('--batch_size', type=int, default=2,
                      help='Number of items to process per batch')

    args = parser.parse_args()

    classifier = ExpenseClassifier(args.company_id)
    
    # Use the appropriate method based on the type argument
    if args.type == 'vendors':
        print("Starting vendor classification...")
        results = classifier.process_vendors(batch_size=args.batch_size)
    else:
        print(f"Starting expense classification with batch size {args.batch_size}...")
        results = classifier.process_expenses(batch_size=args.batch_size)
    
    # Print summary
    if results:
        print(f"\nClassification Summary:")
        print(f"Total classified: {len(results)}")
        
        # Count by classification
        classifications = {}
        for item in results:
            class_type = item.get('classification')
            if class_type in classifications:
                classifications[class_type] += 1
            else:
                classifications[class_type] = 1
        
        print("\nDistribution by classification type:")
        for class_type, count in classifications.items():
            print(f"- {class_type}: {count} items ({(count/len(results))*100:.1f}%)")
            
    print("\nClassification process complete.")