# Wizard-w1 🧙‍♂️

**Wizard-w1** is an advanced AI Data Analyst that empowers you to unlock insights from your data using plain English. It combines a powerful **FastAPI** backend powered by **Ollama (DeepSeek-R1)** with a premium **Next.js** frontend to create a seamless, interactive data analysis experience.

## ✨ Features

-   **Natural Language Interface**: Ask questions about your data in plain English (e.g., "Show me the correlation between tip and total_bill").
-   **Dynamic Visualizations**: Automatically generates and displays interactive plots (Matplotlib/Seaborn) directly in the chat.
-   **Premium UI**: A modern, dark-themed interface with glassmorphism effects, smooth animations, and a responsive design.
-   **Hybrid Intelligence**: Uses a hybrid approach with local LLMs (DeepSeek-R1 via Ollama) for privacy and cost-efficiency.
-   **Dual Modes**:
    -   **Web App**: Full-featured React/Next.js interface.
    -   **CLI**: Robust command-line interface for quick tasks.

## 🏗 Tech Stack

### Frontend
-   **Framework**: Next.js 15 (React 19)
-   **Styling**: Tailwind CSS v4, Lucide React
-   **Features**: Glassmorphism, Custom Animations, Responsive Layout

### Backend
-   **Framework**: FastAPI
-   **AI Engine**: LangChain + Ollama (DeepSeek-R1)
-   **Data Processing**: Pandas, NumPy
-   **Visualization**: Matplotlib, Seaborn

## 🚀 Getting Started

### Prerequisites
-   **Python 3.10+**
-   **Node.js 18+**
-   **Ollama**: Installed and running with the `deepseek-r1` model.

### 1. Setup Ollama (AI Engine)
Ensure Ollama is installed and the model is pulled:
```bash
ollama pull deepseek-r1
```
Start the Ollama server (if you have a low-VRAM GPU, force CPU mode):
```powershell
# Windows PowerShell
$env:OLLAMA_NUM_GPU=0; ollama serve
```

### 2. Setup Backend
Navigate to the backend directory and install dependencies:
```bash
cd backend
pip install -r requirements.txt
```
Start the API server:
```bash
uvicorn api:app --reload --port 8000
```
*The backend will run at `http://localhost:8000`*

### 3. Setup Frontend
Navigate to the frontend directory and install dependencies:
```bash
cd frontend
npm install
```
Start the development server:
```bash
npm run dev
```
*The frontend will run at `http://localhost:3000`*

## 📖 Usage

1.  Open **http://localhost:3000** in your browser.
2.  Upload a CSV file (e.g., `backend/dataset/tips.csv`).
3.  Start chatting! Try asking:
    -   *"Show the first 5 rows"*
    -   *"Plot a histogram of total_bill"*
    -   *"What is the average tip by gender?"*

## 📂 Project Structure

```plaintext
Wizard-w1/
├── backend/                 # FastAPI Server & AI Logic
│   ├── agent.py            # AI Agent implementation
│   ├── api.py              # FastAPI endpoints
│   ├── main.py             # CLI entry point
│   └── ...
├── frontend/                # Next.js Web Application
│   ├── app/                # App Router & Pages
│   ├── components/         # UI Components (Chat, Upload)
│   └── ...
└── ...
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License.
