# Contributing to AStock Trading Agents

Thanks for your interest in contributing! This guide will help you get started.

## Development Setup

```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/astock-trading-agents.git
cd astock-trading-agents

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or: .venv\Scripts\activate  # Windows

# Install in dev mode with all extras
pip install -e ".[dev]"
```

## Project Structure

```
src/astock_trader/
├── agents/       # 15 AI agent definitions
├── dataflows/    # Multi-source data layer (akshare + tushare + mx)
├── graph/        # LangGraph orchestration
├── llm_clients/  # LLM client abstraction
├── cli/          # Typer CLI
└── default_config.py
```

## Coding Conventions

- **Python 3.10+** with type hints on all function signatures
- **snake_case** for functions/variables, **PascalCase** for classes
- **Docstrings** in English (Google style); analysis output in Chinese
- **Log messages** in English via `logging` module
- **NEVER** hardcode API keys — use environment variables only
- **State mutations** through reducer functions only

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=astock_trader --cov-report=term-missing

# Specific test file
pytest tests/test_schemas.py -v
```

## Linting

We use [ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check
ruff check

# Auto-fix
ruff check --fix

# Format check
ruff format --check

# Auto-format
ruff format
```

## Pull Request Process

1. **Fork** the repository and create a feature branch from `master`
2. **Write tests** for any new functionality
3. **Ensure** `pytest tests/ -v` and `ruff check` pass
4. **Commit** with a clear message describing the change
5. **Open a PR** using the provided template
6. **Wait** for review — we aim to respond within 48 hours

## Adding a New Agent

1. Create a `.py` file in the appropriate `agents/` subdirectory
2. Export a `create_xxx(llm)` factory function returning a LangChain `Runnable`
3. Add export to the subdirectory's `__init__.py` and `agents/__init__.py`
4. Register the node in `graph/setup.py`
5. Add state fields to `agents/utils/agent_states.py` if needed
6. Add tests in `tests/test_agents.py`

## Adding a New Data Source

1. Create adapter in `dataflows/` implementing the data interface
2. Register in `dataflows/interface.py` vendor routing
3. Add configuration option to `default_config.py`
4. Add tests in `tests/test_dataflows.py`

## Reporting Issues

- Use the **Bug Report** template for bugs
- Use the **Feature Request** template for new ideas
- Include version, Python version, OS, and LLM provider when relevant

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Please be respectful and constructive.
