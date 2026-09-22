#!/bin/bash

echo "========================================"
echo "Knowledge Agent Desktop - Build"
echo "========================================"
echo ""

# Check Node.js installation
echo "[1/4] Checking Node.js installation..."
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js is not installed"
    echo "Please install Node.js from https://nodejs.org/"
    exit 1
fi
echo "Node.js found: $(node --version)"

# Check npm installation
echo ""
echo "[2/4] Checking npm installation..."
if ! command -v npm &> /dev/null; then
    echo "ERROR: npm is not installed"
    exit 1
fi
echo "npm found: $(npm --version)"

# Install dependencies
echo ""
echo "[3/4] Installing dependencies..."
npm install
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies"
    exit 1
fi

# Build application
echo ""
echo "[4/4] Building application..."
npm run build
if [ $? -ne 0 ]; then
    echo "ERROR: Build failed"
    exit 1
fi

# Package based on platform
echo ""
echo "Packaging for $(uname -s)..."
case "$(uname -s)" in
    Linux*)
        npm run package:linux
        ;;
    Darwin*)
        npm run package:mac
        ;;
    *)
        echo "Unsupported platform: $(uname -s)"
        echo "Please run 'npm run package' manually"
        exit 1
        ;;
esac

if [ $? -ne 0 ]; then
    echo "ERROR: Packaging failed"
    exit 1
fi

echo ""
echo "========================================"
echo "Build completed successfully!"
echo ""
echo "The installer is located in the 'release' folder."
echo "========================================"
