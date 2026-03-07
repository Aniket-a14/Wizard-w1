# 🎨 Wizard w1: Frontend

The frontend of **Wizard w1** is a high-performance, dark-themed dashboard built with **Next.js 16** and **TailwindCSS v4**. It provides a glassmorphic interface for interacting with the AI Data Analyst agent.

## 🚀 Key Features

- **Glassmorphic UI**: Modern aesthetic with frosted glass effects and fluid animations using `framer-motion`.
- **Interactive Chat**: Real-time communication with the Scientific Agent.
- **Agentic Thinking UI**: Live rendering of the Manager (DeepSeek) agent's `<thought>` process as it plans data strategies and performs web searches.
- **Data Visualization**: Dynamic charts and plots powered by `recharts`.
- **Responsive Design**: Fully optimized for various screen sizes.
- **Modern Stack**: Built with React 19 and Next.js 16 (App Router).

## 🛠️ Tech Stack

- **Framework**: [Next.js 16](https://nextjs.org/) (App Router)
- **Styling**: [TailwindCSS v4](https://tailwindcss.com/)
- **Components**: [Radix UI](https://www.radix-ui.com/) & [Shadcn UI](https://ui.shadcn.com/)
- **Charts**: [Recharts](https://recharts.org/)
- **Icons**: [Lucide React](https://lucide.dev/)
- **Animations**: [Framer Motion](https://www.framer.com/motion/)
- **Type Safety**: [TypeScript](https://www.typescriptlang.org/)

## 📦 Getting Started

### 1. Installation

From the `frontend` directory, install the dependencies:

```bash
npm install
```

### 2. Development

Run the development server:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

### 3. Production Build

Create an optimized production build:

```bash
npm run build
npm run start
```

## 📂 Project Structure

- `app/`: Next.js App Router (pages and layouts).
- `components/`: Reusable UI components (Chat, Visualizer, Sidebar).
- `lib/`: Utility functions and shared logic.
- `public/`: Static assets (images, icons).
- `styles/`: Global CSS and Tailwind configuration.

## ⚙️ Environment Variables

The frontend connects to the backend API. Ensure the following variable is configured in a `.env.local` file if necessary:

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | The URL of the FastAPI backend. |

---

Developed as part of the **Wizard w1** project.
