"use client";

import { motion } from "framer-motion";
import { ArrowUp, Sparkles, Terminal } from "lucide-react";
import { useState, useRef, useEffect } from "react";

export default function ChatInterface({ messages = [], onSendMessage, isProcessing }) {
    const [input, setInput] = useState("");
    const scrollRef = useRef(null);

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages]);

    const handleSubmit = (e) => {
        e.preventDefault();
        if (input.trim() && !isProcessing) {
            onSendMessage(input);
            setInput("");
        }
    };

    return (
        <div className="flex flex-col h-[600px] glass-panel rounded-2xl overflow-hidden shadow-2xl shadow-indigo-500/10">

            {/* Terminal Header */}
            <div className="px-4 py-3 bg-slate-900/80 border-b border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <Terminal className="w-4 h-4 text-indigo-400" />
                    <span className="text-xs font-mono text-slate-400">agent_execution_shell — bash — 80x24</span>
                </div>
                <div className="flex gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full bg-slate-700/50" />
                    <div className="w-2.5 h-2.5 rounded-full bg-slate-700/50" />
                </div>
            </div>

            {/* Messages Area */}
            <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto p-4 space-y-4 font-mono text-sm bg-slate-950/50"
            >
                {messages.length === 0 && (
                    <div className="h-full flex flex-col items-center justify-center text-slate-500 gap-3 opacity-50">
                        <Sparkles className="w-8 h-8" />
                        <p>Ready for analysis. Await instructions.</p>
                    </div>
                )}

                {messages.map((msg, i) => (
                    <motion.div
                        key={i}
                        initial={{ opacity: 0, x: msg.role === 'user' ? 20 : -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                        {msg.role === 'assistant' && (
                            <div className="w-6 h-6 rounded bg-indigo-500/20 flex items-center justify-center shrink-0 border border-indigo-500/30">
                                <span className="text-[10px] text-indigo-300">AI</span>
                            </div>
                        )}

                        <div className={`
              max-w-[80%] rounded-lg px-4 py-2 border 
              ${msg.role === 'user'
                                ? 'bg-indigo-600/20 border-indigo-500/30 text-indigo-100'
                                : 'bg-slate-900 border-white/10 text-slate-300'}
            `}>
                            {msg.type === 'code' ? (
                                <code className="block whitespace-pre-wrap text-xs text-emerald-400 bg-black/30 p-2 rounded mt-1 border border-white/5">
                                    {msg.content}
                                </code>
                            ) : (
                                <p>{msg.content}</p>
                            )}
                        </div>
                    </motion.div>
                ))}

                {isProcessing && (
                    <div className="flex items-center gap-2 text-indigo-400 text-xs animate-pulse">
                        <span className="w-2 h-2 bg-indigo-500 rounded-full" />
                        <span>PROCESSING REQUEST...</span>
                    </div>
                )}
            </div>

            {/* Input Area */}
            <form onSubmit={handleSubmit} className="p-3 bg-slate-900 border-t border-white/10 flex gap-2">
                <div className="relative flex-1">
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Enter command or natural language instruction..."
                        className="w-full bg-slate-800/50 border border-white/5 rounded-lg pl-4 pr-4 py-2.5 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500/50 font-mono text-sm"
                    />
                </div>
                <button
                    type="submit"
                    disabled={!input.trim() || isProcessing}
                    className="bg-indigo-600 hover:bg-indigo-500 text-white p-2.5 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {isProcessing ? <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <ArrowUp className="w-5 h-5" />}
                </button>
            </form>
        </div>
    );
}
