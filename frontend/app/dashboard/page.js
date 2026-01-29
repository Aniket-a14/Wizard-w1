"use client";

import { useState } from "react";
import ChatInterface from "../../components/ChatInterface";
import Visualizer from "../../components/Visualizer";
import FileUpload from "../../components/FileUpload";
import { Sparkles } from "lucide-react";

export default function DashboardPage() {
    const [edaSummary, setEdaSummary] = useState(null);
    const [messages, setMessages] = useState([
        { role: "assistant", content: "System initialized. Please upload a dataset to begin analysis." }
    ]);
    const [isProcessing, setIsProcessing] = useState(false);
    const [imageData, setImageData] = useState(null);

    const handleUploadSuccess = (data) => {
        // API returns 'summary', fix key mismatch
        if (data && data.summary) {
            setEdaSummary(data.summary);
            setMessages(prev => [
                ...prev,
                { role: "assistant", content: `Data successfully loaded. ${data.shape[0]} rows, ${data.shape[1]} columns detected.` },
                { role: "assistant", content: "I have analyzed the schema. You can ask me to visualize distributions, detect outliers, or run statistical tests." }
            ]);
        }
    };

    const handleSendMessage = async (text) => {
        setMessages(prev => [...prev, { role: "user", content: text }]);
        setIsProcessing(true);

        try {
            // Fix: Send JSON, not FormData
            const response = await fetch('http://localhost:8000/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: text }),
            });

            if (!response.ok) throw new Error("Analysis failed");

            const data = await response.json();

            // Add Assistant Response
            setMessages(prev => [...prev, { role: "assistant", content: data.response }]);

            // If code was generated (API returns 'code')
            if (data.code) {
                setMessages(prev => [...prev, { role: "assistant", type: "code", content: data.code }]);
            }

            // If image was generated, update visualizer
            if (data.image) {
                setImageData(data.image);
            }

        } catch (error) {
            setMessages(prev => [...prev, { role: "assistant", content: "Error: Failed to execute analysis. Please try again." }]);
        } finally {
            setIsProcessing(false);
        }
    };

    return (
        <div className="h-[calc(100vh-6rem)] flex flex-col gap-6">

            {/* Header / Context */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400 text-glow">
                        Analysis Console
                    </h1>
                    <p className="text-slate-400 text-sm mt-1">
                        Interactive Session {edaSummary ? "• Active Dataset" : "• Idle"}
                    </p>
                </div>
                {/* File Upload Widget */}
                <div className="w-96">
                    <FileUpload onUploadSuccess={handleUploadSuccess} />
                </div>
            </div>

            {/* Main Workspace Grid */}
            <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-0">

                {/* Chat Panel (Left) */}
                <div className="lg:col-span-5 h-full">
                    <ChatInterface
                        messages={messages}
                        onSendMessage={handleSendMessage}
                        isProcessing={isProcessing}
                    />
                </div>

                {/* Visualization Panel (Right) */}
                <div className="lg:col-span-7 h-full">
                    <Visualizer imageData={imageData} />

                    {/* Insights / Stats (Optional, utilizing space) */}
                    {edaSummary && !imageData && (
                        <div className="mt-4 p-4 glass-panel rounded-xl border border-white/5">
                            <div className="flex items-center gap-2 mb-2 text-indigo-400">
                                <Sparkles className="w-4 h-4" />
                                <span className="font-bold text-xs uppercase tracking-wider">Quick Insights</span>
                            </div>
                            <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line font-mono text-xs">
                                {edaSummary}
                            </p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
