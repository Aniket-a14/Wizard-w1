# Contributing to Wizard-w1

First off, thanks for taking the time to contribute! 🎉

The following is a set of guidelines for contributing to Wizard-w1. These are just guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## 🚀 Getting Started

### Prerequisites
*   Node.js 18+
*   Python 3.10+
*   Git

### Installation
1.  **Fork the repo** and clone it locally.
    ```bash
    git clone https://github.com/Aniket-a14/Wizard-w1.git
    cd Wizard-w1
    ```

2.  **Backend Setup**
    ```bash
    cd backend
    pip install -r requirements.txt
    # Create a .env file if needed
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
3.  **Test your changes**.
    *   Frontend: `npm run lint` & `npm run build`
    *   Backend: `flake8 .` & Ensure server runs (`python -m uvicorn app.main:app`)

## 📝 Pull Request Process

1.  Ensure any install or build dependencies are removed before the end of the layer when doing a build.
2.  Update the `README.md` with details of changes to the interface, this includes new environment variables, exposed ports, useful file locations and container parameters.
3.  You may merge the Pull Request in once you have the sign-off of two other developers, or if you do not have permission to do that, you may request the second reviewer to merge it for you.

## 🎨 Code Style

*   **Frontend**: We use standard Prettier/ESLint rules.
*   **Backend**: We follow PEP 8. Please run `flake8` before committing.

## 🐞 Reporting Bugs

Bugs are tracked as GitHub issues. When creating an issue, please explain the problem and include additional details to help maintainers reproduce the problem:
*   Use a clear and descriptive title.
*   Describe the exact steps which reproduce the problem.
*   Provide specific examples to demonstrate the steps.
