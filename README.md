# Expense Tax Deduction Classifier

An intelligent expense classification system that automatically categorizes business expenses into appropriate tax deduction categories (0%, 50%, 100%) using GPT.

## Setup

1. Create and activate a Python virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your OpenAI API key:
```bash
OPENAI_API_KEY=your_api_key_here
```

4. Set up the data directory structure:
```
data/
├── inputs/ (not in git)
│   ├── companyA/
│   │   └── Company A.xlsx
│   └── companyB/
│       └── Company B.xlsx
├── intermediates/
└── outputs/
```

5. Configure `config.json` for each company.
```

## Usage

Run the classification pipeline for a specific company:
```
./command.sh <company_id>
```
For example: `./command.sh A` for Company A

The pipeline runs these scripts in sequence:
1. `build_evaluation_set.py`: Creates evaluation set of known 0% deductible vendors
2. `prepare_vendors.py`: Processes raw expense data and extracts unique vendors
3. `classify_vendors.py`: Classifies vendors using GPT
4. `evaluate_classifications.py`: Evaluates accuracy against known vendors

## Project Structure

```
├── src/
│   ├── build_evaluation_set.py  # Creates evaluation set for accuracy testing
│   ├── prepare_vendors.py       # Processes raw expense data
│   ├── classify_vendors.py      # Main classification logic using GPT
│   └── evaluate_classifications.py  # Evaluates classification accuracy
├── data/
│   ├── inputs/                  # Raw company expense files (not in git)
│   ├── intermediates/           # Processed data and evaluation sets
│   └── outputs/                 # Classification results and summaries
├── command.sh                   # Main execution script
├── config.json                  # Company-specific configurations
├── requirements.txt             # Python dependencies
└── .env                        # Environment variables (not in git)
```

## Output Files

Each company's output directory contains:
- `classified_vendors.json`: Detailed vendor classifications
- `classified_expenses.json`: Individual expense classifications
- `vendors_deductible_0.json`: List of 0% deductible vendors
- `vendors_deductible_50.json`: List of 50% deductible vendors
- `vendors_deductible_100.json`: List of 100% deductible vendors
- `final_summary.csv`: Summary statistics of classifications

## Classification Rules

- Entertainment venues (0%): Bars, clubs, venues, recreational activities
- Meals (50%): Restaurants, cafes, food delivery, catering
- Employee events (100%): Company-wide celebrations, team events

## Implementation Details

### Model Choice
- Using GPT-3.5-turbo via OpenAI API for efficient and cost-effective classification
- Good balance between accuracy and cost
- Faster response times compared to GPT-4

### Classification Approach
- Zero-shot classification with carefully crafted prompts
- Chain-of-thought reasoning to improve accuracy
- Validation of outputs against known rules

### Limitations
- Requires clear expense descriptions
- May need human review for ambiguous cases
- Cost scales with number of API calls

### Future Improvements
- Implement fine-tuning for better accuracy
- Add batch processing for efficiency
- Create UI for manual review of uncertain cases
- Add test suite for validation 