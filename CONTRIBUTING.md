# Contributing to Wizard-w1

First off, thanks for taking the time to contribute! 🎉

The following is a set of guidelines for contributing to **Wizard-w1**. These ensure the codebase remains healthy, secure, and professional.

## 🚀 Getting Started

### Prerequisites
*   **Node.js 20+** (LTS recommended)
*   **Python 3.11+**
*   **Docker** & Docker Compose (for local verification)
*   **Ollama** (optional, for local LLM testing)

### Installation
1.  **Fork the repo** and clone it locally.
    ```bash
    git clone https://github.com/Aniket-a14/Wizard-w1.git
    cd Wizard-w1
    ```

2.  **Backend Setup**
    ```bash
    cd backend
    python -m venv .venv
    source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    ```

3.  **Frontend Setup**
    ```bash
    cd frontend
    npm install
    ```

## 🛠️ Development Workflow

1.  **Create a branch** for your feature or fix.
    ```bash
    git checkout -b feature/amazing-feature
    ```
2.  **Make your changes**.
3.  **Test your changes locally**.
    *   **Frontend**: `npm run lint` & `npm run build`
    *   **Backend**: `ruff check .` & `pytest tests/`
    *   **Docker**: `docker-compose up --build`

## 📝 Pull Request Process

1.  **Use the Template**: Every PR must fill out the provided [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md).
2.  **CI Checks**: Your PR must pass all GitHub Actions (CI, Security/CodeQL, Cross-Platform) before it can be merged.
3.  **Human Review**: All PRs **require at least one approval** from a core maintainer (e.g., `@Aniket-a14`).
4.  **Model Disclaimer**: If your changes involve the Scientific Agent, please note that weights are not shared in the repository. You must verify logic changes with your own locally trained weights.

## 🎨 Code Style

*   **Frontend**: We use standard ESLint and Prettier rules.
*   **Backend**: We follow PEP 8 and use **Ruff** for linting/formatting. Please run `ruff check .` before committing.
*   **Types**: We encourage the use of TypeScript (Frontend) and Python Type Hints (Backend/Pydantic).

## 🐞 Reporting Bugs

Bugs are tracked as GitHub issues. When creating an issue, please explain the problem and include:
*   A clear and descriptive title.
*   The exact steps which reproduce the problem.
*   Relevant logs or error messages from the Console or Terminal.
