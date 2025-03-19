#!/bin/bash

# Check if company ID is provided
if [ $# -eq 0 ]; then
    echo "Error: Company ID is required"
    echo "Usage: ./command.sh <company_id>"
    exit 1
fi

COMPANY_ID=$1

# Activate virtual environment
source venv/bin/activate

echo "Processing Company ${COMPANY_ID}..."

# Create directory structure
mkdir -p "data/inputs/company${COMPANY_ID}"
mkdir -p "data/intermediates/company${COMPANY_ID}"
mkdir -p "data/outputs/company${COMPANY_ID}"

# Only run build_evaluation_set for Company A
if [ "$COMPANY_ID" = "A" ]; then
    echo "Building evaluation set..."
    python3 src/build_evaluation_set.py
fi

# Run the Python scripts
python3 src/prepare_vendors.py "${COMPANY_ID}"
python3 src/classify_vendors.py "${COMPANY_ID}"
python3 src/evaluate_classifications.py "${COMPANY_ID}" 