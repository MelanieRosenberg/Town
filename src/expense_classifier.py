import pandas as pd
import os
from dotenv import load_dotenv
from typing import List, Dict
import openai
import json

# Load environment variables
load_dotenv()

class ExpenseClassifier:
    def __init__(self):
        # Initialize OpenAI client
        self.client = openai.OpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )
        
        # Define deduction categories
        self.DEDUCTION_CATEGORIES = {
            0: "0% deductible (No deduction allowed)",
            50: "50% deductible (Standard business meals)",
            100: "100% deductible (Employee social events)"
        }
        
        # Common vendor patterns for quick classification
        self.VENDOR_PATTERNS = {
            # 0% deductible patterns
            0: [
                'soho house', 'soho ludlow', 'soho works', 'soho home',  # Soho House related entities
                'club', 'theater', 'cinema', 'entertainment',
                'golf', 'sport', 'venue', 'lounge', 'bar', 'pub',
                'membership', 'dues', 'subscription'
            ],
            # 50% deductible patterns
            50: [
                'restaurant', 'cafe', 'coffee', 'deli', 'bistro', 'kitchen',
                'uber eats', 'doordash', 'grubhub', 'seamless', 'caviar',
                'food', 'catering', 'pizzeria', 'sushi', 'thai', 'chinese',
                'mexican', 'burger', 'steak', 'seafood', 'bakery',
                'starbucks', 'dunkin', 'mcdonald', 'chipotle', 'sweetgreen',
                'juice', 'sandwich', 'bagel', 'diner'
            ],
            # 100% deductible patterns
            100: [
                'holiday party', 'christmas party', 'team building',
                'all hands', 'company event', 'staff party', 'employee event'
            ]
        }

    def load_company_data(self, company: str) -> pd.DataFrame:
        """Load and preprocess company data from Excel file."""
        if company == "A":
            # Read the Excel file
            df = pd.read_excel("Company A.xlsx")
            
            # Find the row index where the actual data starts (where Date column begins)
            start_idx = df[df.iloc[:, 0] == "Date"].index[0]
            
            # Read the file again, starting from the correct row
            df = pd.read_excel("Company A.xlsx", skiprows=start_idx)
            
            # Set the correct column names
            df.columns = ["Date", "Transaction Type", "Num", "Adj", "Name", "Memo/Description", "Split", "Amount", "Balance"]
            
            # Add unique ID from original ledger
            df['UniqueID'] = df.index + 1
            
            # Filter for specific Split category
            mask = df["Split"].str.contains("6250 General & Administrative:Meals & Entertainment", na=False, case=False)
            filtered_df = df[mask].copy()
            
            # Convert Amount to numeric, handling any non-numeric values
            filtered_df["Amount"] = pd.to_numeric(filtered_df["Amount"], errors="coerce")
            
            return filtered_df
            
        elif company == "B":
            # Read the Excel file
            df = pd.read_excel("Company B.xlsx")
            
            # Find the row index where the actual data starts
            start_idx = df[df.iloc[:, 0] == "Date"].index[0]
            
            # Read the file again, starting from the correct row
            df = pd.read_excel("Company B.xlsx", skiprows=start_idx)
            
            # Add unique ID from original ledger
            df['UniqueID'] = df.index + 1
            
            # Rename columns based on the first row
            df.columns = df.iloc[0]
            df = df.iloc[1:].reset_index(drop=True)
            
            # Filter for MECE Meals or Meals & Entertainment
            mask = (
                df["Memo"].str.contains("MECE Meals|Meals & Entertainment", na=False, case=False) |
                df["Split"].str.contains("MECE Meals|Meals & Entertainment", na=False, case=False)
            )
            return df[mask]
        else:
            raise ValueError(f"Unknown company: {company}")

    def _check_vendor_patterns(self, vendor: str, description: str) -> int:
        """Quick check for known vendor patterns before using GPT-4."""
        text_to_check = f"{vendor} {description}".lower()
        
        # More thorough text cleanup
        text_to_check = text_to_check.replace('*', ' ')  # Handle PayPal style entries
        text_to_check = text_to_check.replace('paypal', '')  # Remove PayPal references
        text_to_check = ''.join(c for c in text_to_check if c.isalnum() or c.isspace())  # Remove punctuation
        text_to_check = ' '.join(text_to_check.split())  # Normalize whitespace
        
        # Check for 100% patterns first (most specific)
        for pattern in self.VENDOR_PATTERNS[100]:
            pattern_clean = ''.join(c for c in pattern if c.isalnum() or c.isspace())
            if pattern_clean in text_to_check:
                return 100
                
        # Check for 0% patterns next
        for pattern in self.VENDOR_PATTERNS[0]:
            pattern_clean = ''.join(c for c in pattern if c.isalnum() or c.isspace())
            if pattern_clean in text_to_check:
                return 0
                
        # Check for 50% patterns last (most common)
        for pattern in self.VENDOR_PATTERNS[50]:
            pattern_clean = ''.join(c for c in pattern if c.isalnum() or c.isspace())
            if pattern_clean in text_to_check:
                return 50
                
        return -1  # No pattern match found

    def classify_expense(self, description: str, amount: float, vendor: str = None) -> tuple[int, bool, str]:
        """
        Classify a single expense using pattern matching first, then LLM if needed.
        Returns tuple of (deduction_percentage, is_uncertain, uncertainty_reason)
        """
        # Try pattern matching first
        if vendor or description:
            pattern_match = self._check_vendor_patterns(vendor or "", description or "")
            if pattern_match != -1:
                print(f"Pattern match found: {pattern_match}% deductible")
                return (pattern_match, False, "")
        
        print("No pattern match found, using GPT-4...")
        prompt = self._build_classification_prompt(description, amount, vendor)
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": """You are a tax expert specializing in meal and entertainment expense deductions. 
                    Your task is to classify expenses based on vendor type and description.
                    
                    First line must be ONLY ONE of these numbers: 0, 50, or 100
                    Second line must be ONLY the word 'certain' or 'uncertain'
                    If uncertain, third line should briefly explain why (max 50 chars)
                    
                    CLASSIFICATION RULES - BE AGGRESSIVE IN CATEGORIZING:
                    
                    50% DEDUCTIBLE (Default for any food/beverage establishment):
                    - ANY restaurant, cafe, coffee shop, or food vendor
                    - ANY food delivery service
                    - ANY catering service (unless clearly for company event)
                    - ANY establishment primarily serving food/beverages
                    - When in doubt about a food vendor, classify as 50%
                    
                    0% DEDUCTIBLE:
                    - Entertainment venues and clubs
                    - Membership dues and subscriptions
                    - Recreational facilities
                    - Bars and lounges (primary purpose entertainment)
                    - Sporting events and venues
                    - ALL Soho House related venues (including Soho House, Soho Works, 
                      Soho Home, Soho Ludlow, etc.) - these are private members clubs
                    
                    100% DEDUCTIBLE (Must be explicitly clear):
                    - Company holiday parties
                    - Company-wide events
                    - Team building events
                    - All-hands meetings
                    
                    DECISION RULES:
                    1. If vendor name contains any food/restaurant terms - classify 50%
                    2. If vendor is clearly entertainment/club/bar - classify 0%
                    3. If description mentions company event - classify 100%
                    4. If vendor contains "Soho" and appears to be Soho House related - classify 0%
                    5. Only mark uncertain if COMPLETELY UNABLE to determine vendor type
                    
                    Example responses:
                    For "UBER EATS":
                    50
                    certain
                    
                    For "SOHO LUDLOW INC":
                    0
                    certain
                    
                    For "SOHO HOUSE":
                    0
                    certain
                    
                    For "2024 HOLIDAY PARTY":
                    100
                    certain"""},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=50
            )
            
            lines = response.choices[0].message.content.strip().split('\n')
            
            if len(lines) >= 2:
                classification = lines[0].strip()
                certainty = lines[1].strip().lower()
                reason = lines[2].strip() if len(lines) > 2 and certainty == 'uncertain' else ""
                
                if classification in ['0', '50', '100']:
                    return (int(classification), 
                           certainty == 'uncertain',
                           reason)
                else:
                    print(f"Invalid classification result: {classification}")
                    return (0, True, "Invalid classification format")
            else:
                print("Invalid response format")
                return (0, True, "Invalid response format")
                
        except Exception as e:
            print(f"Error classifying expense: {e}")
            return (0, True, f"Error: {str(e)}")

    def _build_classification_prompt(self, description: str, amount: float, vendor: str = None) -> str:
        """Build prompt for expense classification."""
        prompt = f"Classify this expense based on vendor type and description:\n"
        if vendor and vendor.strip() != "":
            prompt += f"Vendor: {vendor}\n"
        prompt += f"Description: {description}\n"
        prompt += f"Amount: ${amount:,.2f}"
        return prompt

    def process_company_data(self, company: str) -> Dict:
        """Process all expenses for a company and return summary."""
        df = self.load_company_data(company)
        results = {
            0: {"count": 0, "total": 0.0},
            50: {"count": 0, "total": 0.0},
            100: {"count": 0, "total": 0.0}
        }
        
        # Create a new DataFrame to store classifications
        classified_expenses = []
        
        print(f"\nFound {len(df)} expenses to classify.")
        
        for i, (_, row) in enumerate(df.iterrows(), 1):
            description = str(row.get('Memo/Description', '')) if company == "A" else str(row.get('Memo', ''))
            amount = abs(float(row.get('Amount', 0)))
            vendor = str(row.get('Name', ''))
            split_category = str(row.get('Split', ''))
            unique_id = row.get('UniqueID')
            
            print(f"\nClassifying expense {i}/{len(df)}:")
            print(f"Original Ledger ID: {unique_id}")
            print(f"Description: {description}")
            print(f"Amount: ${amount:,.2f}")
            print(f"Vendor: {vendor}")
            print(f"Category: {split_category}")
            
            deduction, is_uncertain, uncertainty_reason = self.classify_expense(description, amount, vendor)
            print(f"Classification: {deduction}% deductible")
            if is_uncertain:
                print(f"Uncertain: {uncertainty_reason}")
            
            # Store classification result
            classified_expenses.append({
                'UniqueID': unique_id,
                'Description': description,
                'Amount': amount,
                'Vendor': vendor,
                'Category': split_category,
                'Classification': deduction,
                'is_uncertain': is_uncertain,
                'uncertainty_reason': uncertainty_reason
            })
            
            results[deduction]["count"] += 1
            results[deduction]["total"] += amount
        
        # Create and save classified expenses DataFrame
        classified_df = pd.DataFrame(classified_expenses)
        output_file = f"expenses_company_{company}.csv"
        classified_df.to_csv(output_file, index=False)
        print(f"\nClassified expenses saved to {output_file}")
        
        # Print uncertainty statistics
        uncertain_count = classified_df['is_uncertain'].sum()
        print(f"\nUncertainty Statistics:")
        print(f"Total uncertain classifications: {uncertain_count} ({(uncertain_count/len(classified_df))*100:.1f}%)")
        
        return results

def main():
    classifier = ExpenseClassifier()
    
    # Process both companies
    for company in ["A", "B"]:
        print(f"\nProcessing Company {company}...")
        results = classifier.process_company_data(company)
        
        # Print summary
        print(f"\nResults for Company {company}:")
        for deduction, data in results.items():
            print(f"{classifier.DEDUCTION_CATEGORIES[deduction]}:")
            print(f"Count: {data['count']}")
            print(f"Total: ${data['total']:,.2f}")

if __name__ == "__main__":
    main() 