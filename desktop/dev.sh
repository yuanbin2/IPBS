#!/bin/bash

echo "========================================"
echo "Knowledge Agent Desktop - Development"
echo "========================================"
echo ""

# Check Node.js installation
echo "[1/3] Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js is not installed"
    echo "Please install Node.js from https://nodejs.org/"
    exit 1
fi
echo "Node.js found: $(node --version)"

# Check npm installation
echo ""
echo "[2/3] Checking npm installation..."
if ! command -v npm &> /dev/null; then
    echo "ERROR: npm is not installed"
    exit 1
fi
echo "npm found: $(npm --version)"

# Install dependencies
echo ""
echo "[3/3] Installing dependencies..."
npm install
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies"
    exit 1
fi

# Start development server
echo ""
echo "Starting development server..."
echo ""
echo "The desktop app will open automatically."
echo "Press Ctrl+C to stop the development server."
echo ""
npm run dev
