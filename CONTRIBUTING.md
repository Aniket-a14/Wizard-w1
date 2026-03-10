# Contributing to Wizard w1 🧙‍♂️

First off, thank you for considering contributing to **Wizard w1**! It is people like you who make the open-source community an amazing place to learn, inspire, and create.

This guide provides the necessary information to get you started and ensures your contributions meet our standards for code quality, security, and architectural integrity within our **Pure Ollama Architecture**.

---

## 🏗️ Architectural Core: Pure Ollama Multi-Agent System (MAS)
Wizard w1 operates on a decoupled, production-grade **Multi-Agent Architecture** running natively through Ollama. When contributing, keep this execution flow in mind:

1.  **Scientific Agent (Manager - DeepSeek-R1)**: Handles deterministic reasoning, analytical planning, web-crawling for context, and evaluation generation.
2.  **Code Generator (Worker - Qwen2.5-Coder)**: Exclusively translates manager blueprints into AST-compliant Pandas and SciPy expressions.
3.  **The Council (Adjudication)**: A suite of specialized heuristic checks that grade the execution before returning the payload to the frontend.
4.  **Hardened Sandbox (Docker)**: All code is isolated in zero-trust Docker containers prior to execution to prevent execution bleed.

> [!IMPORTANT]
> The project architecture is strictly **Local-First & Pure Ollama (v2.3.0+)**. Avoid introducing cloud-based dependencies (e.g., OpenAI bindings) or heavy local mapping tools like `torch` or `transformers` directly into `backend/`. 

---

## 🚀 Environment Setup

### Prerequisites
*   **Node.js 20+** (LTS) & **Python 3.11+**
*   **Docker Desktop** (with minimum 8GB+ RAM allocated for the worker environments)
*   **Ollama Daemon** installed and running on your host machine natively.

### 1. Repository Setup
```bash
# Fork the repo on GitHub, then clone your fork:
git clone https://github.com/YOUR_USERNAME/Wizard-w1.git
cd Wizard-w1
git remote add upstream https://github.com/Aniket-a14/Wizard-w1.git
```

### 2. Model Hydration (Host Machine)
We rely entirely on standard Ollama endpoints. Pull the brains locally:
```bash
ollama pull deepseek-r1:1.5b
ollama pull qwen2.5-coder:1.5b
```

### 3. Backend Installation (Python API)
When developing the backend without Docker (for direct debugging):
```bash
cd backend
python -m venv .venv

# Activate:
# Unix/MacOS: source .venv/bin/activate
# Windows: .venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

### 4. Frontend Installation (Next.js Client)
```bash
cd ../frontend
npm ci
```

---

## 🛠️ Development Cycle

### Branching Strategy
We follow a disciplined Git Flow. Please name your branches descriptively:
*   `feature/` (e.g., `feature/custom-visualization-charts`)
*   `fix/` (e.g., `fix/docker-socket-binding`)
*   `docs/` (e.g., `docs/update-rest-api`)
*   `refactor/` (e.g., `refactor/abstract-guardrails`)

### Standards & Quality
Before committing, ensure your code passes our CI gates:

**Backend (Python - FastAPI)**
*   **Linting**: We exclusively use **Ruff**. Run `ruff check . --fix` and `ruff format .`.
*   **Types**: Type execution flows defensively. Rely on Pydantic `BaseModel` for all REST transfers.
*   **Tests**: Maintain test coverage. Run `pytest` locally. Mock Ollama responses when testing AST parsing logic.

**Frontend (React/TypeScript - Next.js)**
*   **Linting**: `npm run lint`
*   **Type Check**: `npx tsc --noEmit`
*   **Styles**: Strictly `TailwindCSS v4`. Do not introduce large UI libraries without prior RFC approval.
*   **Build**: Ensure `npm run build` concludes completely without SC / CSR warnings.

---

## 📝 Pull Request Process

1.  **Sync**: Ensure your fork is up-to-date with `upstream/master`.
2.  **Commit Messages**: We enforce conventional commits (`feat:`, `fix:`, `chore:`, etc.).
3.  **PR Template**: Fill out the provided Pull Request Template completely.
4.  **Local Verification**: If modifying the Glassmorphic UI, attach screenshots or a short visual GIF in your PR.
5.  **Review**: At least one core maintainer must approve the PR. All Github Actions (CodeQL, Linting, Testing) must pass `green`.

---

## 🛡️ Security Policy
If you discover a security vulnerability, please **do not open a public issue.** See our detailed [SECURITY.md](./SECURITY.md) guidelines. We prioritize patches for:
*   Docker Sandbox escape vectors.
*   AST / `eval()` logic bypassing.
*   FastAPI endpoint injection.

---

## 🌈 Community

*   **Issues**: Search existing issues before opening a new one. Provide reproducible error states.
*   **Discussions**: Use the GitHub Discussions tab for "RFC" (Request for Comments) or architectural questions.

Thank you for contributing to the orchestration layer of the future! 🧙‍♂️🦾
