import { useState, useRef, useEffect } from 'react';
import { Send, Bot, User, Loader2 } from 'lucide-react';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export default function ChatInterface({ isFileLoaded }) {
    const [messages, setMessages] = useState([]);
    const [input, setInput] = useState('');
    const [isLoading, setIsLoading] = useState(false);
    const messagesEndRef = useRef(null);

    const scrollToBottom = () => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!input.trim() || isLoading || !isFileLoaded) return;

        const userMessage = input.trim();
        setInput('');
        setMessages(prev => [...prev, { role: 'user', content: userMessage }]);
        setIsLoading(true);

        try {
            const response = await fetch('http://localhost:8000/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: userMessage }),
            });

            if (!response.ok) {
                throw new Error('Failed to send message');
            }

            const data = await response.json();
            setMessages(prev => [...prev, {
                role: 'assistant',
                content: data.response,
                code: data.code,
                image: data.image
            }]);
        } catch (error) {
            console.error('Error:', error);
            setMessages(prev => [...prev, { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' }]);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className="flex flex-col h-[600px] bg-slate-900/50 backdrop-blur-xl rounded-2xl shadow-2xl border border-slate-800/50 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-6 space-y-6 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
                {messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center p-8 animate-fade-in">
                        <div className="w-20 h-20 bg-gradient-to-br from-blue-500/20 to-purple-500/20 rounded-2xl flex items-center justify-center mb-6 backdrop-blur-sm border border-white/5">
                            <Bot className="w-10 h-10 text-blue-400" />
                        </div>
                        <h3 className="text-xl font-semibold text-white mb-2">Ready to Analyze</h3>
                        <p className="text-slate-400 max-w-sm">
                            Start chatting with your data assistant! Ask questions, request visualizations, or explore trends.
                        </p>
                        {!isFileLoaded ? (
                            <div className="mt-6 px-4 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-red-300 text-sm">
                                Please upload a dataset first
                            </div>
                        ) : null}
                    </div>
                ) : null}

                {messages.map((msg, index) => (
                    <div key={index} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in`}>
                        <div className={`max-w-[85%] rounded-2xl p-4 shadow-lg ${msg.role === 'user'
                            ? 'bg-gradient-to-r from-blue-600 to-blue-500 text-white rounded-br-none'
                            : 'bg-slate-800/80 text-slate-200 rounded-bl-none border border-slate-700/50'
                            }`}>
                            <div className="flex items-center gap-2 mb-2 opacity-75">
                                {msg.role === 'user' ? <User size={14} /> : <Bot size={14} />}
                                <span className="text-xs font-semibold uppercase tracking-wider">
                                    {msg.role === 'user' ? 'You' : 'Wizard'}
                                </span>
                            </div>

                            <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>

                            {msg.code ? (
                                <div className="mt-4 bg-slate-950 rounded-xl border border-slate-800 overflow-hidden relative group/code">
                                    <div className="bg-slate-900/50 px-4 py-2 border-b border-slate-800 flex items-center justify-between">
                                        <div className="flex items-center gap-2">
                                            <div className="flex gap-1.5">
                                                <div className="w-2.5 h-2.5 rounded-full bg-red-500/20"></div>
                                                <div className="w-2.5 h-2.5 rounded-full bg-yellow-500/20"></div>
                                                <div className="w-2.5 h-2.5 rounded-full bg-green-500/20"></div>
                                            </div>
                                            <span className="text-xs text-slate-500 font-mono ml-2">Python Code</span>
                                        </div>
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => navigator.clipboard.writeText(msg.code)}
                                            className="h-6 text-xs text-slate-500 hover:text-white transition-colors opacity-0 group-hover/code:opacity-100"
                                        >
                                            Copy
                                        </Button>
                                    </div>
                                    <div className="p-4 overflow-x-auto">
                                        <pre className="text-xs font-mono text-blue-300 leading-relaxed">{msg.code}</pre>
                                    </div>
                                </div>
                            ) : null}

                            {msg.image ? (
                                <div className="mt-4 rounded-xl overflow-hidden border border-slate-700/50 bg-white relative w-full h-auto min-h-[300px]">
                                    <Image
                                        src={`data:image/png;base64,${msg.image}`}
                                        alt="Generated plot"
                                        width={800}
                                        height={600}
                                        className="w-full h-auto"
                                    />
                                </div>
                            ) : null}
                        </div>
                    </div>
                ))}

                {isLoading ? (
                    <div className="flex justify-start animate-fade-in">
                        <div className="bg-slate-800/50 rounded-2xl rounded-bl-none p-4 flex items-center gap-3 border border-slate-700/50">
                            <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                            <span className="text-sm text-slate-400">Analyzing data...</span>
                        </div>
                    </div>
                ) : null}
                <div ref={messagesEndRef} />
            </div>

            <form onSubmit={handleSubmit} className="p-4 bg-slate-900/80 border-t border-slate-800/50 backdrop-blur-md">
                <div className="flex gap-3">
                    <Input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder={isFileLoaded ? "Ask a question about your data..." : "Upload a file to start chatting"}
                        disabled={!isFileLoaded || isLoading}
                        className="flex-1 bg-slate-800/50 border-slate-700 text-white placeholder:text-slate-500 focus-visible:ring-blue-500/50"
                    />
                    <Button
                        type="submit"
                        disabled={!isFileLoaded || isLoading || !input.trim()}
                        className="bg-gradient-to-r from-blue-600 to-blue-500 text-white hover:from-blue-500 hover:to-blue-400 shadow-lg shadow-blue-500/20 px-6 py-2 h-10"
                    >
                        <Send size={20} />
                    </Button>
                </div>
            </form>
        </div>
    );
}
