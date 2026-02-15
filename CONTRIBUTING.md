# Contributing to Wizard w1 🧙‍♂️

First off, thank you for considering contributing to **Wizard w1**! It’s people like you who make the open-source community an amazing place to learn, inspire, and create.

This guide provides the necessary information to get you started and ensures your contributions meet our standards for code quality, security, and architectural integrity.

---

## 🏗️ Architectural Core: Multi-Agent System (MAS)
Wizard w1 operates on an enterprise-grade **Multi-Agent Architecture**. When contributing, keep this flow in mind:
1.  **Scientific Agent (Manager)**: Handles reasoning, planning, and evaluation.
2.  **Specialist Council**: Visualizers, Statisticians, and Architects adjudicate results.
3.  **Hardened Sandbox**: All code is executed in isolated Docker containers with strict resource limits and warm pooling.
4.  **WorkingMemory**: Persistent RAG-based context allows for session-aware development.

> [!IMPORTANT]
> The project is strictly **Local-First**. Avoid introducing cloud-based dependencies or proprietary APIs unless explicitly approved.

---

## 🚀 Environment Setup

### Prerequisites
*   **Node.js 20+** (LTS) & **Python 3.11+**
*   **Docker Desktop** (with 8GB+ RAM allocated)
*   **CUDA GPU** (Recommended): A GPU with 8GB+ VRAM is required for smooth 4-bit model inference.
*   **Hugging Face Account**: You need a free HF token if you plan to use `download_models.py`.

### 1. Repository Setup
```bash
# Fork the repo on GitHub, then clone your fork:
git clone https://github.com/YOUR_USERNAME/Wizard-w1.git
cd Wizard-w1
git remote add upstream https://github.com/Aniket-a14/Wizard-w1.git
```

### 2. Backend Installation (Python)
We use a standard virtual environment approach.
```bash
cd backend
python -m venv .venv

# Activate:
# Windows:
.venv\Scripts\Activate.ps1
# Unix/MacOS:
source .venv/bin/activate

pip install -r requirements.txt

# CRITICAL: Hydrate the local models
python download_models.py
```

### 3. Frontend Installation (Next.js)
```bash
cd ../frontend
npm install
```

---

## 🛠️ Development Cycle

### Branching Strategy
We follow a simplified Git Flow. Please name your branches descriptively:
*   `feature/` (e.g., `feature/custom-plotting-tool`)
*   `fix/` (e.g., `fix/agent-memory-leak`)
*   `docs/` (e.g., `docs/update-api-reference`)
*   `refactor/` (e.g., `refactor/clean-api-middleware`)

### Standards & Quality
Before committing, ensure your code passes our quality gates:

**Backend (Python)**
*   **Linting**: We use **Ruff**. Run `ruff check . --fix` and `ruff format .`.
*   **Types**: Use type hints everywhere. We rely on Pydantic for validation.
*   **Tests**: Run `pytest` from the root or `backend/` directory.

**Frontend (TypeScript)**
*   **Linting**: `npm run lint`
*   **Type Check**: `npx tsc --noEmit`
*   **Build**: `npm run build` (Ensures no server-side rendering issues).

---

## 📝 Pull Request Process

1.  **Sync**: Ensure your fork is up-to-date with `upstream/master`.
2.  **Commit Messages**: We prefer conventional commits (e.g., `feat: add support for parquet files`).
3.  **PR Template**: Fill out the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md) completely.
4.  **Local Verification**: Record a short demo or attach screenshots if your PR introduces UI/UX changes.
5.  **Review**: At least one core maintainer (e.g., `@Aniket-a14`) must approve the PR.

---

## 🛡️ Security Policy
If you discover a security vulnerability, please **do not open a public issue**. Instead, email the maintainers directly or use the GitHub Private Vulnerability Reporting feature. We prioritize fixes for:
*   Sandbox escape vulnerabilities.
*   Insecure code execution logic.
*   Sensitive data exposure in logs.

---

## 🌈 Community
*   **Issues**: Search existing issues before opening a new one.
*   **Discussions**: Use the GitHub Discussions tab for "RFC" (Request for Comments) or architectural questions.

Thank you for helping us build the future of agentic data science! 🧙‍♂️🦾
