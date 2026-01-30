"use client";

import { useState } from 'react';
import { Upload, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';

export default function FileUpload({ onUploadSuccess }) {
    const [isUploading, setIsUploading] = useState(false);
    const [error, setError] = useState('');
    const [fileInfo, setFileInfo] = useState(null);

    const handleFileChange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        if (!file.name.endsWith('.csv')) {
            setError('System Protocol: Only .csv format is authorized.');
            return;
        }

        setIsUploading(true);
        setError('');

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('http://localhost:8000/upload', {
                method: 'POST',
                body: formData,
            });

            if (!response.ok) {
                throw new Error('Upload failed');
            }

            const data = await response.json();
            setFileInfo({
                name: data.filename,
                rows: data.shape[0],
                cols: data.shape[1]
            });
            onUploadSuccess(data);
        } catch (err) {
            console.error(err);
            setError('Upload Error: Connection refused or file rejected.');
            onUploadSuccess(false);
        } finally {
            setIsUploading(false);
        }
    };

    return (
        <div className="w-full">
            {!fileInfo ? (
                <div className="relative group">
                    <div className="absolute inset-0 bg-indigo-500/20 blur-xl opacity-0 group-hover:opacity-100 transition-opacity rounded-xl" />

                    <label className="relative flex flex-col items-center justify-center w-full h-32 border-2 border-dashed border-slate-700 hover:border-indigo-500 rounded-xl cursor-pointer bg-slate-900/50 hover:bg-slate-900/80 transition-all overflow-hidden group">

                        <div className="flex items-center gap-4 z-10">
                            <div className={`p-3 rounded-lg bg-slate-800 border border-white/5 group-hover:scale-110 transition-transform duration-300 ${isUploading ? 'animate-pulse' : ''}`}>
                                {isUploading ? <Loader2 className="w-6 h-6 text-indigo-400 animate-spin" /> : <Upload className="w-6 h-6 text-indigo-400" />}
                            </div>
                            <div className="text-left">
                                <p className="text-sm font-medium text-slate-200 group-hover:text-white transition-colors">
                                    {isUploading ? 'Ingesting Data stream...' : 'Upload Dataset'}
                                </p>
                                <p className="text-xs text-slate-500">
                                    .CSV Supported • max 50MB
                                </p>
                            </div>
                        </div>

                        <input
                            type="file"
                            accept=".csv"
                            onChange={handleFileChange}
                            disabled={isUploading}
                            className="hidden"
                        />

                        {/* Grid Pattern Background */}
                        <div className="absolute inset-0 bg-[url('/grid.svg')] opacity-[0.05] pointer-events-none" />
                    </label>
                </div>
            ) : (
                <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex items-center justify-between p-4 bg-emerald-500/10 border border-emerald-500/20 rounded-xl"
                >
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-emerald-500/20 rounded-lg">
                            <CheckCircle className="w-5 h-5 text-emerald-400" />
                        </div>
                        <div>
                            <p className="text-sm font-medium text-emerald-100">{fileInfo.name}</p>
                            <p className="text-xs text-emerald-400/70">{fileInfo.rows.toLocaleString()} rows • {fileInfo.cols} cols</p>
                        </div>
                    </div>
                    <button
                        onClick={() => { setFileInfo(null); onUploadSuccess(false); }}
                        className="px-3 py-1.5 text-xs bg-emerald-900/50 hover:bg-emerald-900 text-emerald-200 rounded-lg border border-emerald-500/20 transition-colors"
                    >
                        Reset
                    </button>
                </motion.div>
            )}

            {error && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="mt-3 flex items-center gap-2 text-xs text-red-300 bg-red-500/10 border border-red-500/20 p-3 rounded-lg"
                >
                    <AlertCircle className="w-4 h-4" />
                    {error}
                </motion.div>
            )}
        </div>
    );
}
