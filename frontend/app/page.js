"use client";

import { motion } from "framer-motion";
import { ArrowRight, BarChart3, BrainCircuit, Terminal } from "lucide-react";
import Link from "next/link";

export default function LandingPage() {
    return (
        <main className="min-h-screen relative overflow-hidden flex flex-col items-center justify-center p-6">

            {/* Background Elements */}
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_10%,_rgba(120,40,200,0.15),_transparent_40%)] pointer-events-none" />
            <div className="absolute inset-0 bg-[url('/grid.svg')] opacity-10 pointer-events-none" />

            {/* Hero Section */}
            <div className="z-10 text-center max-w-5xl mx-auto space-y-8">

                {/* Badge */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.5 }}
                    className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-indigo-500/30 bg-indigo-500/10 backdrop-blur-md"
                >
                    <span className="flex h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
                    <span className="text-xs font-mono text-cyan-200 tracking-wider">SYSTEM v2.0 ONLINE</span>
                </motion.div>

                {/* Title */}
                <motion.h1
                    initial={{ opacity: 0, y: 30 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.7, delay: 0.1 }}
                    className="text-6xl md:text-8xl font-bold tracking-tight text-white"
                >
                    Data Science <br />
                    <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-violet-500 text-glow">
                        Autopilot
                    </span>
                </motion.h1>

                {/* Subtitle */}
                <motion.p
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.7, delay: 0.2 }}
                    className="text-lg md:text-xl text-slate-400 max-w-2xl mx-auto leading-relaxed"
                >
                    Stop writing boilerplate. Let the <strong>Scientific Agent</strong> plan, validate, and execute your analysis in seconds.
                </motion.p>

                {/* Actions */}
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.7, delay: 0.3 }}
                    className="flex flex-col sm:flex-row gap-4 justify-center items-center pt-8"
                >
                    <Link href="/dashboard" className="group relative px-8 py-4 bg-white text-slate-950 rounded-full font-bold text-lg hover:bg-cyan-50 transition-all flex items-center gap-3">
                        Launch Console
                        <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                        <div className="absolute inset-0 rounded-full bg-indigo-500 blur-xl opacity-20 group-hover:opacity-40 transition-opacity -z-10" />
                    </Link>

                    <button className="px-8 py-4 rounded-full border border-slate-700 text-slate-300 font-medium hover:bg-slate-800/50 hover:text-white transition-colors">
                        View Documentation
                    </button>
                </motion.div>

            </div>

            {/* Feature Grid (Floating) */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mt-24 max-w-6xl w-full">
                <FeatureCard
                    icon={<BrainCircuit className="w-6 h-6 text-violet-400" />}
                    title="Automated Planning"
                    desc="The agent formulates a statistical plan before writing a single line of code."
                    delay={0.4}
                />
                <FeatureCard
                    icon={<Terminal className="w-6 h-6 text-cyan-400" />}
                    title="Secure Sandbox"
                    desc="Code execution happens in a strictly isolated environment for safety."
                    delay={0.5}
                />
                <FeatureCard
                    icon={<BarChart3 className="w-6 h-6 text-emerald-400" />}
                    title="Instant Insights"
                    desc="From raw CSV to production-grade visualization in under 5 seconds."
                    delay={0.6}
                />
            </div>

        </main>
    );
}

function FeatureCard({ icon, title, desc, delay }) {
    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay }}
            className="glass-card p-6 rounded-2xl border border-white/5 hover:border-white/10 transition-colors"
        >
            <div className="w-12 h-12 rounded-full bg-slate-900/50 flex items-center justify-center mb-4 border border-white/5">
                {icon}
            </div>
            <h3 className="text-xl font-bold text-white mb-2">{title}</h3>
            <p className="text-slate-400 leading-relaxed">{desc}</p>
        </motion.div>
    );
}
