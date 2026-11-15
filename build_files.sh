#!/bin/bash
echo "=== Starting TicketMitra Vercel Build ==="

# 1. Create and activate virtual environment to comply with PEP 668
python3 -m venv .venv 2>/dev/null || python -m venv .venv 2>/dev/null || true

if [ -f ".venv/bin/activate" ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
fi

# 2. Install dependencies (with fallback for --break-system-packages)
echo "Installing dependencies from requirements.txt..."
python3 -m pip install -r requirements.txt --break-system-packages 2>/dev/null || python3 -m pip install -r requirements.txt || pip install -r requirements.txt --break-system-packages 2>/dev/null || pip install -r requirements.txt

# 3. Collect static files
echo "Collecting static files..."
python3 manage.py collectstatic --noinput --clear || python manage.py collectstatic --noinput --clear

echo "=== Vercel Build Completed Successfully ==="
