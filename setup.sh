#!/bin/bash
echo "Creating virtual environment..."
python3 -m venv venv

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing requirements..."
pip install -r requirements.txt

echo "Done! To activate the environment later, run:"
echo "source venv/bin/activate"
echo "use deactive to remove the venv"
