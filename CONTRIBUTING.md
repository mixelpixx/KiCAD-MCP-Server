# Contributing to KiCAD MCP Server

Thank you for your interest in contributing to the KiCAD MCP Server! This guide will help you get started with development.

## Table of Contents

- [Development Environment Setup](#development-environment-setup)
- [Project Structure](#project-structure)
- [Architecture Overview](#architecture-overview)
- [Development Workflow](#development-workflow)
- [Testing](#testing)
- [Code Style](#code-style)
- [Pull Request Process](#pull-request-process)
- [Roadmap & Planning](#roadmap--planning)

---

## Development Environment Setup

### Prerequisites

- **KiCAD 9.0 or higher** - [Download here](https://www.kicad.org/download/)
- **Node.js v18+** - [Download here](https://nodejs.org/)
- **Python 3.9+** - Comes bundled with KiCAD (macOS builds ship Python 3.9; Linux/Windows builds ship Python 3.11)
- **Git** - For version control

### Platform-Specific Setup

#### Linux (Ubuntu/Debian)

```bash
# Install KiCAD 9.0 from official PPA
sudo add-apt-repository --yes ppa:kicad/kicad-9.0-releases
sudo apt-get update
sudo apt-get install -y kicad kicad-libraries

# Install Node.js (if not already installed)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Clone the repository
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd kicad-mcp-server

# Install Node.js dependencies
npm install

# Install Python dependencies
pip3 install -r requirements-dev.txt

# Build TypeScript
npm run build

# Run tests
npm test
pytest
```

#### Windows

```powershell
# Install KiCAD 9.0 from https://www.kicad.org/download/windows/

# Install Node.js from https://nodejs.org/

# Clone the repository
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd kicad-mcp-server

# Install Node.js dependencies
npm install

# Install Python dependencies
pip install -r requirements-dev.txt

# Build TypeScript
npm run build

# Run tests
npm test
pytest
```

#### macOS

```bash
# Install KiCAD 9.0 from https://www.kicad.org/download/macos/

# Install Node.js via Homebrew
brew install node

# Clone the repository
git clone https://github.com/mixelpixx/KiCAD-MCP-Server.git
cd kicad-mcp-server

# Install Node.js dependencies
npm install

# Install Python dependencies
pip3 install -r requirements-dev.txt

# Build TypeScript
npm run build

# Run tests
npm test
pytest
```

### Pre-commit Hooks

This project uses [pre-commit](https://pre-commit.com/) to run linters and formatters automatically before each commit. Pre-commit hooks prevent noisy formatting diffs caused by different IDE configurations across contributors, catch common mistakes and type errors before they reach code review, and ensure every commit in the repository meets the same quality baseline — so reviewers can focus on logic and design rather than style issues.

**All contributors must install pre-commit hooks after cloning the repo:**

```bash
# Install pre-commit (if not already installed)
pip install pre-commit

# Install the git hooks
pre-commit install

# (Optional) Run against all files to verify setup
pre-commit run --all-files
```

> **Important:** Do not use `git commit --no-verify` to bypass pre-commit hooks. The hooks enforce code quality checks (Black, isort, Prettier, flake8, mypy, ESLint) that must pass before code is merged. If a hook fails, fix the underlying issue rather than skipping the check.

---

## Project Structure

```
kicad-mcp-server/
├── .github/
│   └── workflows/        # CI/CD pipelines
├── config/               # Configuration examples
│   ├── linux-config.example.json
│   ├── windows-config.example.json
│   └── macos-config.example.json
├── docs/                 # Documentation
├── python/               # Python interface layer
│   ├── commands/         # KiCAD command handlers
│   ├── integrations/     # External API integrations (JLCPCB, Digikey)
│   ├── utils/            # Utility modules
│   └── kicad_interface.py  # Main Python entry point
├── src/                  # TypeScript MCP server
│   ├── tools/            # MCP tool implementations
│   ├── resources/        # MCP resource implementations
│   ├── prompts/          # MCP prompt implementations
│   └── server.ts         # Main server
├── tests/                # Test suite
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── dist/                 # Compiled JavaScript (generated)
├── node_modules/         # Node dependencies (generated)
├── package.json          # Node.js configuration
├── tsconfig.json         # TypeScript configuration
├── pytest.ini            # Pytest configuration
├── requirements.txt      # Python production dependencies
└── requirements-dev.txt  # Python dev dependencies
```

---

## Architecture Overview

The KiCAD MCP Server is organized into several key components:

- **TypeScript MCP Server** (`src/`) - Handles MCP protocol communication and tool routing
- **Python KiCAD Interface** (`python/`) - Interfaces with KiCAD's Python API (pcbnew)
- **Tool Router** - Organizes 122+ tools into 8 discoverable categories
- **Resource System** - Provides dynamic project/board state information
- **Prompt System** - Offers context-aware design prompts

**Current Tool Count:** 122+ tools across 8 categories (direct + routed)

For detailed architecture information, see `docs/ROUTER_ARCHITECTURE.md`.

---

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes

- Edit TypeScript files in `src/`
- Edit Python files in `python/`
- Add tests for new features

### 3. Build & Test

```bash
# Build TypeScript
npm run build

# Run TypeScript linter
npm run lint

# Run Python formatter
black python/

# Run Python type checker
mypy python/

# Run all tests
npm test
pytest

# Run specific test file
pytest tests/test_platform_helper.py -v

# Run with coverage
pytest --cov=python --cov-report=html
```

### 4. Commit Changes

```bash
git add .
git commit -m "feat: Add your feature description"
```

**Commit Message Convention:**

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Adding/updating tests
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks

### 5. Push and Create Pull Request

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

---

## Testing

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest -m unit

# Integration tests (requires KiCAD installed)
pytest -m integration

# Platform-specific tests
pytest -m linux      # Linux tests only
pytest -m windows    # Windows tests only

# With coverage report
pytest --cov=python --cov-report=term-missing

# Verbose output
pytest -v

# Stop on first failure
pytest -x
```

### Writing Tests

Tests should be placed in `tests/` directory:

```python
# tests/test_my_feature.py
import pytest

@pytest.mark.unit
def test_my_feature():
    """Test description"""
    # Arrange
    expected = "result"

    # Act
    result = my_function()

    # Assert
    assert result == expected

@pytest.mark.integration
@pytest.mark.linux
def test_linux_integration():
    """Integration test for Linux"""
    # This test will only run on Linux in CI
    pass
```

---

## Code Style

### Python

We use **Black** for code formatting and **MyPy** for type checking.

```bash
# Format all Python files
black python/

# Check types
mypy python/

# Run linter
pylint python/
```

**Python Style Guidelines:**

- Use type hints for all function signatures
- Use pathlib.Path for file paths (not os.path)
- Use descriptive variable names
- Add docstrings to all public functions/classes
- Follow PEP 8

**Example:**

```python
from pathlib import Path
from typing import List, Optional

def find_kicad_libraries(search_path: Path) -> List[Path]:
    """
    Find all KiCAD symbol libraries in the given path.

    Args:
        search_path: Directory to search for .kicad_sym files

    Returns:
        List of paths to found library files

    Raises:
        ValueError: If search_path doesn't exist
    """
    if not search_path.exists():
        raise ValueError(f"Search path does not exist: {search_path}")

    return list(search_path.glob("**/*.kicad_sym"))
```

### TypeScript

We use **ESLint** and **Prettier** for TypeScript.

```bash
# Format TypeScript files
npx prettier --write "src/**/*.ts"

# Run linter
npx eslint src/
```

**TypeScript Style Guidelines:**

- Use interfaces for data structures
- Use async/await for asynchronous code
- Use descriptive variable names
- Add JSDoc comments to exported functions

---

## Pull Request Process

1. **Update Documentation** - If you change functionality, update docs
2. **Add Tests** - All new features should have tests
3. **Run CI Locally** - Ensure all tests pass before pushing
4. **Create PR** - Use a clear, descriptive title
5. **Request Review** - Tag relevant maintainers
6. **Address Feedback** - Make requested changes
7. **Merge** - Maintainer will merge when approved

### PR Checklist

- [ ] Code follows style guidelines
- [ ] All tests pass locally
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commit messages follow convention
- [ ] No merge conflicts
- [ ] CI/CD pipeline passes

---

## Roadmap & Planning

We track work using GitHub Projects and Issues:

- **GitHub Projects** - High-level roadmap and sprints
- **GitHub Issues** - Specific bugs and features
- **GitHub Discussions** - Design discussions and proposals

### Current Priorities (Week 1-4)

1. ✅ Linux compatibility fixes
2. ✅ Platform-agnostic path handling
3. ✅ CI/CD pipeline setup
4. 🔄 Migrate to KiCAD IPC API
5. ⏳ Add JLCPCB integration
6. ⏳ Add Digikey integration

See [docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md) for the complete 12-week roadmap.

---

## Getting Help

- **GitHub Discussions** - Ask questions, propose ideas
- **GitHub Issues** - Report bugs, request features
- **Discord** - Real-time chat (link TBD)

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

## Thank You! 🎉

Your contributions make this project better for everyone. We appreciate your time and effort!
