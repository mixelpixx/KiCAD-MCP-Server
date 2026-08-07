#!/bin/bash
# KiCAD MCP Server - Linux Installation Script
# Supports Ubuntu/Debian-based distributions

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored messages
print_info() { echo -e "${BLUE}ℹ${NC} $1"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }

# Header
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║          KiCAD MCP Server - Linux Installation                ║"
echo "║                                                                ║"
echo "║  This script will install:                                     ║"
echo "║  - KiCAD 9.0                                                   ║"
echo "║  - Node.js 20.x                                                ║"
echo "║  - Python dependencies                                         ║"
echo "║  - Build the TypeScript server                                 ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    print_error "This script is for Linux only. Detected: $OSTYPE"
    exit 1
fi

# Check for Ubuntu/Debian
if ! command -v apt-get &> /dev/null; then
    print_warning "This script is optimized for Ubuntu/Debian"
    print_warning "For other distributions, please install manually"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Function to check if command exists
command_exists() {
    command -v "$1" &> /dev/null
}

NODE_REQUIRED="^20.19.0, ^22.13.0, or >=24.0.0"

node_version_supported() {
    local version="${1#v}"
    if [[ ! "$version" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
        return 1
    fi

    local major="${BASH_REMATCH[1]}"
    local minor="${BASH_REMATCH[2]}"

    (( (major == 20 && minor >= 19) ||
       (major == 22 && minor >= 13) ||
       major >= 24 ))
}

install_supported_node() {
    print_info "Installing Node.js 20.x..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs

    local installed_version
    installed_version=$(node --version)
    if ! node_version_supported "$installed_version"; then
        print_error "Installed Node.js $installed_version is unsupported. Required: $NODE_REQUIRED."
        exit 1
    fi
    print_success "Supported Node.js installed: $installed_version"
}

# Step 1: Install KiCAD 9.0
print_info "Step 1/5: Installing KiCAD 9.0..."
if command_exists kicad; then
    KICAD_VERSION=$(kicad-cli version 2>/dev/null | head -n 1 || echo "unknown")
    print_success "KiCAD is already installed: $KICAD_VERSION"
else
    print_info "Adding KiCAD PPA and installing..."
    sudo add-apt-repository --yes ppa:kicad/kicad-9.0-releases
    sudo apt-get update
    sudo apt-get install -y kicad kicad-libraries
    print_success "KiCAD 9.0 installed"
fi

# Verify KiCAD Python module
print_info "Verifying KiCAD Python module..."
if python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())" 2>/dev/null; then
    PCBNEW_VERSION=$(python3 -c "import pcbnew; print(pcbnew.GetBuildVersion())")
    print_success "KiCAD Python module (pcbnew) found: $PCBNEW_VERSION"
else
    print_warning "KiCAD Python module (pcbnew) not found in default Python path"
    print_warning "You may need to set PYTHONPATH manually"
fi

# Step 2: Install Node.js
print_info "Step 2/5: Installing Node.js 20.x..."
if command_exists node; then
    NODE_VERSION=$(node --version)
    if node_version_supported "$NODE_VERSION"; then
        print_success "Supported Node.js is already installed: $NODE_VERSION"
    else
        print_warning "Node.js $NODE_VERSION is unsupported. Required: $NODE_REQUIRED."
        install_supported_node
    fi
else
    install_supported_node
fi

# Step 3: Install Python dependencies
print_info "Step 3/5: Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip3 install --user -r requirements.txt
    print_success "Python dependencies installed"
else
    print_warning "requirements.txt not found - skipping Python dependencies"
fi

# Step 4: Install Node.js dependencies
print_info "Step 4/5: Installing Node.js dependencies..."
if [ -f "package.json" ]; then
    npm install
    print_success "Node.js dependencies installed"
else
    print_error "package.json not found! Are you in the correct directory?"
    exit 1
fi

# Step 5: Build TypeScript
print_info "Step 5/5: Building TypeScript..."
npm run build
print_success "TypeScript build complete"

# Final checks
echo ""
print_info "Running final checks..."

# Check if dist directory was created
if [ -d "dist" ]; then
    print_success "dist/ directory created"
else
    print_error "dist/ directory not found - build may have failed"
    exit 1
fi

# Test platform helper
print_info "Testing platform detection..."
if python3 python/utils/platform_helper.py > /dev/null 2>&1; then
    print_success "Platform helper working"
else
    print_warning "Platform helper test failed"
fi

# Installation complete
echo ""
echo "╔═══════════════════════════════════════════════════════════════╗"
echo "║                 🎉 Installation Complete! 🎉                   ║"
echo "╚═══════════════════════════════════════════════════════════════╝"
echo ""
print_success "KiCAD MCP Server is ready to use!"
echo ""
print_info "Next steps:"
echo "  1. Configure Cline in VSCode with the path to dist/index.js"
echo "  2. Set PYTHONPATH in Cline config (see README.md)"
echo "  3. Restart VSCode"
echo "  4. Test with: 'Create a new KiCAD project named TestProject'"
echo ""
print_info "For detailed configuration, see:"
echo "  - README.md (Linux section)"
echo "  - config/linux-config.example.json"
echo ""
print_info "To run tests:"
echo "  pytest tests/"
echo ""
print_info "Need help? Check docs/LINUX_COMPATIBILITY_AUDIT.md"
echo ""
