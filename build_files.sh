#!/bin/bash
echo "=== Building TicketMitra for Vercel Deployment ==="
python3 -m pip install -r requirements.txt
python3 manage.py collectstatic --noinput --clear
echo "=== Build Completed Successfully ==="
