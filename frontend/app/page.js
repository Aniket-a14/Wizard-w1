'use client';

import { useState } from 'react';
import FileUpload from './components/FileUpload';
import ChatInterface from './components/ChatInterface';

export default function Home() {
    const [isFileLoaded, setIsFileLoaded] = useState(false);

    return (
        <main className="min-h-screen p-8 font-sans text-white">
            <div className="max-w-5xl mx-auto animate-fade-in">
                <header className="mb-12 text-center space-y-4">
                    <div className="inline-block p-1 rounded-full bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500 mb-4">
                        <div className="bg-slate-950 rounded-full px-4 py-1">
                            <span className="text-xs font-medium tracking-wider uppercase bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
                                AI Powered Analytics
                            </span>
                        </div>
                    </div>
                    <h1 className="text-5xl md:text-6xl font-extrabold tracking-tight mb-2">
                        <span className="bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400">
                            Wizard
                        </span>
                        <span className="text-slate-200"> Data Analyst</span>
                    </h1>
                    <p className="text-lg text-slate-400 max-w-2xl mx-auto leading-relaxed">
                        Upload your dataset and unlock insights instantly with our advanced AI.
                        Just ask questions in plain English.
                    </p>
                </header>

                <div className="space-y-8 animate-slide-up">
                    <FileUpload onUploadSuccess={setIsFileLoaded} />
                    <ChatInterface isFileLoaded={isFileLoaded} />
                </div>
            </div>
        </main>
    );
}
