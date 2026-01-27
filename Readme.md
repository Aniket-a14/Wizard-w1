# 🧙‍♂️ Wizard w1

**Advanced AI Data Analyst Platform** powered by **Qwen2.5-Coder** and **Agentic Workflows**.

Wizard w1 is an autonomous data science agent capable of performing complex analysis, statistical testing, and visualization from natural language instructions. It features a modern, glassmorphic UI and a robust scalable backend.

![Project Banner](https://img.shields.io/badge/Status-Production%20Ready-success) ![License](https://img.shields.io/badge/License-MIT-blue)

## 🚀 Key Features

*   **🤖 Autonomous Agent**: Understands messy data and executes multi-step Python code (Pandas, Scikit-learn, Statsmodels).
*   **📚 Wizard-Analyst-Instruct-500k**: Trained on a massive custom dataset of 500,000 instruction-code pairs across 6 domains.
*   **🧠 Intelligent Memory**: Uses a RAG-lite "Knowledge Base" for dynamic few-shot prompting.
*   **⚡ High-Performance UI**:
    *   Built with **Next.js 16 (Turbopack)** & **shadcn/ui**.
    *   Premium Glassmorphism design with `framer-motion` animations.
    *   Optimized with `next/image` and React Server Components.
*   **🛡️ Secure Execution**: AST-based code validation and "Silent Execution" mode.

## 🛠️ Tech Stack

### Frontend
*   **Framework**: Next.js 16 (App Router)
*   **Styling**: Tailwind CSS v4, shadcn/ui
*   **Icons**: Lucide React
*   **State**: React Hooks (Optimized)

### Backend
*   **API**: FastAPI (Async)
*   **Model**: Qwen2.5-Coder-1.5B (Fine-tuned via LoRA)
*   **Data Processing**: Pandas, NumPy, Scikit-learn
*   **Dataset Engine**: Custom Dynamic Schema Engine (Stream-based generation)

## 🏗️ Architecture

```mermaid
graph TD
    User[User] -->|Upload CSV| FE[Frontend (Next.js)]
    User -->|Ask Question| FE
    FE -->|API Request| BE[Backend (FastAPI)]
    
    subgraph "Backend Core"
        BE -->|Load Data| DS[Data Service]
        BE -->|Generate Code| AS[Agent Service]
        
        AS -->|Retrieve Examples| KB[(Knowledge Base JSON)]
        AS -->|Inference| LLM[Qwen2.5-Coder]
        
        AS -->|Execute Safe Code| Py[Python Runtime]
        Py -->|Return Results| BE
    end
    
    subgraph "Training Pipeline"
        DG[Dataset Generator] -->|Create 500k Pairs| Train[Instruction Dataset]
        Train -->|LoRA Fine-Tuning| LLM
    end
```

## ⚡ Getting Started

### Prerequisites
*   Node.js 18+
*   Python 3.10+
*   CUDA-enabled GPU (optional, for local training)

### Installation

1.  **Clone the repository**
    ```bash
    git clone https://github.com/yourusername/wizard-analyst.git
    cd wizard-analyst
    ```

2.  **Backend Setup**
    ```bash
    cd backend
    pip install -r requirements.txt
    python3 -m uvicorn app.main:app --reload
    ```

3.  **Frontend Setup**
    ```bash
    cd frontend
    npm install
    npm run dev
    ```

## 🧪 "Skills" & Best Practices Incorporated

This project was built using advanced engineering practices:

*   **Senior Data Scientist**:
    *   Implemented **LoRA** (Low-Rank Adaptation) for efficient fine-tuning.
    *   Curated a **500k row instruction dataset** (`instruction_code_dataset.csv`) using a Dynamic Schema Engine.
    *   Integrated complex libraries: `statsmodels` (ARIMA), `scipy` (T-tests), `plotly`.

*   **Senior Backend Engineer**:
    *   Modular **FastAPI** architecture (`app/api`, `app/services`, `app/core`).
    *   **Global Exception Handling** and structured logging with `loguru`.
    *   Stream-optimized data generation (`csv.DictWriter`).

*   **Senior Frontend Engineer**:
    *   **Production-Ready React**: `next/image`, component memoization (`StatCard` refactor), text-safe rendering.
    *   **shadcn/ui Integration**: Systematic design system adoption.
    *   **SEO & Metadata**: Proper Open Graph tags and layout optimization.

## 📊 Dataset
The model is trained on **Wizard-Analyst-Instruct-500k**, a synthetic dataset covering:
*   **Domains**: Retail, Healthcare, Finance, Real Estate, Education, Tech.
*   **Tasks**: Cleaning, EDA, Statistical Testing, ML Modeling, Visualization.
*   **Availability**: [Link to your Kaggle Dataset]

## 📜 License
MIT
