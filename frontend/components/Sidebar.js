"use client";

import { motion } from "framer-motion";
import { Database, History, Home, Settings, Terminal } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const menuItems = [
    { icon: Home, label: "Home", href: "/dashboard" },
    { icon: Database, label: "Datasets", href: "/dashboard/datasets" },
    { icon: History, label: "History", href: "/dashboard/history" },
    { icon: Settings, label: "Settings", href: "/dashboard/settings" },
];

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <motion.aside
            initial={{ x: -20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            className="w-64 h-screen border-r border-white/10 bg-slate-950/50 backdrop-blur-xl flex flex-col fixed left-0 top-0 z-50"
        >
            {/* Logo Area */}
            <div className="p-6 border-b border-white/5 flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
                    <Terminal className="w-5 h-5 text-white" />
                </div>
                <span className="font-bold text-lg tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
                    Wizard<span className="font-light">AI</span>
                </span>
            </div>

            {/* Navigation */}
            <nav className="flex-1 p-4 space-y-2">
                {menuItems.map((item) => {
                    const isActive = pathname === item.href;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200 group relative overflow-hidden ${isActive
                                    ? "text-white bg-white/5 border border-white/10"
                                    : "text-slate-400 hover:text-white hover:bg-white/5"
                                }`}
                        >
                            {isActive && (
                                <motion.div
                                    layoutId="activeTab"
                                    className="absolute inset-0 bg-indigo-500/10"
                                />
                            )}
                            <item.icon className={`w-5 h-5 ${isActive ? "text-indigo-400" : "group-hover:text-indigo-300"}`} />
                            <span className="font-medium">{item.label}</span>
                        </Link>
                    );
                })}
            </nav>

            {/* Connection Status */}
            <div className="p-4 border-t border-white/5">
                <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-slate-900/50 border border-white/5">
                    <div className="relative">
                        <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                        <div className="absolute inset-0 rounded-full bg-emerald-500 blur-sm opacity-50" />
                    </div>
                    <div className="flex flex-col">
                        <span className="text-xs font-semibold text-slate-300">System Online</span>
                        <span className="text-[10px] text-slate-500">v2.4.0 • latency 12ms</span>
                    </div>
                </div>
            </div>
        </motion.aside>
    );
}
