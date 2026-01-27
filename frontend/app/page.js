'use client';

import { useState } from 'react';
import FileUpload from './components/FileUpload';
import ChatInterface from './components/ChatInterface';
import Dashboard from './components/Dashboard';

export default function Home() {
    const [isFileLoaded, setIsFileLoaded] = useState(false);
    const [edaData, setEdaData] = useState(null);

    const handleUploadSuccess = (data) => {
        setIsFileLoaded(true);
        setEdaData(data.eda_summary);
    };

    return (
        <main className="min-h-screen p-6 md:p-12 font-sans bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-slate-900 via-slate-950 to-black text-white selection:bg-blue-500/30">
            <div className="max-w-7xl mx-auto animate-fade-in space-y-12">

                {/* Header Section */}
                <header className="text-center space-y-6">
                    <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800/50 border border-slate-700/50 backdrop-blur-md mb-2">
                        <span className="relative flex h-2 w-2">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
                        </span>
                        <span className="text-xs font-medium text-slate-300 tracking-wide uppercase">AI Data Analyst Frame</span>
                    </div>

                    <h1 className="text-5xl md:text-7xl font-extrabold tracking-tight">
                        <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-indigo-400 to-purple-400">
                            Wizard
                        </span>
                        <span className="text-slate-200"> Analyst</span>
                    </h1>

                    <p className="text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
                        Upload your CSV and let our advanced AI models uncover hidden patterns, generate visualizations, and answer your toughest questions instantly.
                    </p>
                </header>

                {/* Main Interaction Area */}
                <div className="space-y-8">
                    <FileUpload onUploadSuccess={handleUploadSuccess} />

                    {/* Dashboard only appears when data is loaded */}
                    {edaData && <Dashboard edaSummary={edaData} />}

                    <ChatInterface isFileLoaded={isFileLoaded} />
                </div>
            </div>
        </main>
    );
}
