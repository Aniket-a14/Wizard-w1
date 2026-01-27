'use client';

import { useState } from 'react';
import { Upload, CheckCircle, AlertCircle, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

export default function FileUpload({ onUploadSuccess }) {
    const [isUploading, setIsUploading] = useState(false);
    const [error, setError] = useState('');
    const [fileInfo, setFileInfo] = useState(null);

    const handleFileChange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        if (!file.name.endsWith('.csv')) {
            setError('Please upload a CSV file');
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
            setError('Failed to upload file. Please try again.');
            onUploadSuccess(false);
        } finally {
            setIsUploading(false);
        }
    };

    return (
        <Card className="bg-slate-900/50 backdrop-blur-xl border-slate-800/50 shadow-2xl">
            <CardContent className="p-8">
                <h2 className="text-xl font-semibold mb-6 flex items-center gap-3 text-slate-200">
                    <div className="p-2 bg-blue-500/10 rounded-lg">
                        <FileText className="text-blue-400 w-5 h-5" />
                    </div>
                    Dataset Upload
                </h2>

                {!fileInfo ? (
                    <div className="group relative border-2 border-dashed border-slate-700 rounded-xl p-12 text-center hover:border-blue-500/50 hover:bg-blue-500/5 transition-all duration-300">
                        <input
                            type="file"
                            accept=".csv"
                            onChange={handleFileChange}
                            disabled={isUploading}
                            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed z-10"
                        />
                        <div className="flex flex-col items-center gap-4">
                            <div className={`p-4 rounded-full bg-slate-800 group-hover:bg-slate-700 transition-colors ${isUploading ? 'animate-pulse' : ''}`}>
                                <Upload className={`w-8 h-8 ${isUploading ? 'text-blue-400' : 'text-slate-400 group-hover:text-blue-400'} transition-colors`} />
                            </div>
                            <div className="space-y-1">
                                <p className="text-lg font-medium text-slate-300 group-hover:text-blue-300 transition-colors">
                                    {isUploading ? 'Uploading dataset...' : 'Drop your CSV file here'}
                                </p>
                                <p className="text-sm text-slate-500">
                                    or click to browse
                                </p>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="bg-green-500/10 border border-green-500/20 rounded-xl p-6 flex items-center justify-between backdrop-blur-sm">
                        <div className="flex items-center gap-4">
                            <div className="bg-green-500/20 p-3 rounded-full">
                                <CheckCircle className="w-6 h-6 text-green-400" />
                            </div>
                            <div>
                                <p className="font-medium text-green-200 text-lg">{fileInfo.name}</p>
                                <p className="text-sm text-green-400/80">
                                    {fileInfo.rows.toLocaleString()} rows × {fileInfo.cols} columns
                                </p>
                            </div>
                        </div>
                        <Button
                            variant="ghost"
                            onClick={() => {
                                setFileInfo(null);
                                onUploadSuccess(false);
                            }}
                            className="text-slate-400 hover:text-white hover:bg-slate-800"
                        >
                            Change File
                        </Button>
                    </div>
                )}

                {error ? (
                    <div className="mt-4 flex items-center gap-3 text-sm text-red-200 bg-red-500/10 border border-red-500/20 p-4 rounded-xl animate-fade-in">
                        <AlertCircle size={18} className="text-red-400" />
                        {error}
                    </div>
                ) : null}
            </CardContent>
        </Card>
    );
}


