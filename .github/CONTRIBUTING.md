# Contributing to PathFinderAI

Thank you for your interest in contributing to PathFinderAI! We welcome contributions from everyone, whether it's fixing bugs, adding new features, or improving documentation.

## Code of Conduct
Please note that this project is released with a [Contributor Code of Conduct](CODE_OF_CONDUCT.md). By participating in this project, you agree to abide by its terms.

## Getting Started

1. **Fork the repository** on GitHub.
2. **Clone your fork locally**:
   ```bash
   git clone https://github.com/YOUR-USERNAME/PathFinderAI.git
   cd PathFinderAI
   ```
3. **Set up the environment**:
   ```bash
   python -m venv .venv3_11
   # Windows: .venv3_11\Scripts\activate
   # Linux/Mac: source .venv3_11/bin/activate
   pip install -r requirements_crewai.txt
   pip install -e .
   ```
4. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-amazing-feature
   ```

## Making Changes

- Ensure your code follows the existing style. We use `ruff` for linting.
- Add or update tests as necessary in the `tests/` directory.
- Run the linter and tests before committing:
  ```bash
  ruff check src/ scripts/
  pytest tests/
  ```

## Committing

This project uses **Release Please** to automate versioning and changelog generation. Therefore, your commit messages MUST follow the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification.

Examples:
- `feat: add new weather agent to crewai workflow`
- `fix: resolve issue with gpx path parsing`
- `docs: update setup instructions`

## Submitting a Pull Request

1. Push your branch to your fork on GitHub.
2. Open a Pull Request against the `main` branch of this repository.
3. Fill out the PR template completely.
4. Ensure all CI checks pass.

Questions? Open an issue or start a discussion!
