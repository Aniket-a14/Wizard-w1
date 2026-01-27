'use client';

import { BarChart, Hash, AlertTriangle, Layers, Table as TableIcon, FileSpreadsheet } from 'lucide-react';
import { Card, CardContent } from "@/components/ui/card"
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from "@/components/ui/table"

const StatCard = ({ icon: Icon, label, value, subtext, color = "blue" }) => (
    <Card className={`bg-slate-900/40 backdrop-blur-md border-slate-800/50 hover:border-${color}-500/30 transition-all duration-300 group`}>
        <CardContent className="p-6">
            <div className="flex items-center justify-between mb-4">
                <div className={`p-3 rounded-xl bg-${color}-500/10 group-hover:bg-${color}-500/20 transition-colors`}>
                    <Icon className={`w-6 h-6 text-${color}-400`} />
                </div>
                {subtext ? <span className={`text-xs font-mono text-${color}-400/80 bg-${color}-500/10 px-2 py-1 rounded-full`}>{subtext}</span> : null}
            </div>
            <h3 className="text-3xl font-bold text-slate-100 mb-1 tracking-tight">{value}</h3>
            <p className="text-slate-400 font-medium text-sm">{label}</p>
        </CardContent>
    </Card>
);

export default function Dashboard({ edaSummary }) {
    if (!edaSummary) return null;

    const { shape, missing_values, column_types, head } = edaSummary;
    const [rows, cols] = shape;

    // Calculate total missing cells
    const totalCells = rows * cols;
    const totalMissing = Object.values(missing_values).reduce((a, b) => a + b, 0);
    const missingPercentage = ((totalMissing / totalCells) * 100).toFixed(1);

    return (
        <div className="space-y-8 animate-slide-up">
            {/* Quick Stats Row */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <StatCard
                    icon={Hash}
                    label="Total Rows"
                    value={rows.toLocaleString()}
                    color="blue"
                />
                <StatCard
                    icon={Layers}
                    label="Total Columns"
                    value={cols.toLocaleString()}
                    color="purple"
                />
                <StatCard
                    icon={AlertTriangle}
                    label="Missing Values"
                    value={`${missingPercentage}%`}
                    subtext={`${totalMissing.toLocaleString()} cells`}
                    color={parseFloat(missingPercentage) > 5 ? "yellow" : "green"}
                />
                <StatCard
                    icon={FileSpreadsheet}
                    label="Data Structure"
                    value="Tabular"
                    subtext="CSV Loaded"
                    color="pink"
                />
            </div>

            {/* Main Content Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

                {/* Column Types */}
                <Card className="lg:col-span-1 bg-slate-900/40 backdrop-blur-xl border-slate-800/50">
                    <CardContent className="p-8">
                        <h3 className="text-xl font-semibold mb-6 flex items-center gap-2 text-slate-200">
                            <BarChart className="w-5 h-5 text-purple-400" />
                            Column Types
                        </h3>
                        <div className="space-y-4">
                            {Object.entries(column_types).map(([col, type]) => (
                                <div key={col} className="flex items-center justify-between group">
                                    <span className="text-slate-300 font-medium truncate max-w-[150px]" title={col}>{col}</span>
                                    <span className={`text-xs px-3 py-1 rounded-full border border-slate-700 font-mono 
                                        ${type === 'object' ? 'bg-orange-500/10 text-orange-400 border-orange-500/20' :
                                            type.includes('int') || type.includes('float') ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' :
                                                'bg-slate-800 text-slate-400'}`}>
                                        {type}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </CardContent>
                </Card>

                {/* Data Preview (Head) */}
                <Card className="lg:col-span-2 bg-slate-900/40 backdrop-blur-xl border-slate-800/50 overflow-hidden flex flex-col">
                    <CardContent className="p-8 flex-1 flex flex-col">
                        <h3 className="text-xl font-semibold mb-6 flex items-center gap-2 text-slate-200">
                            <TableIcon className="w-5 h-5 text-blue-400" />
                            Data Preview
                        </h3>
                        <div className="rounded-xl border border-slate-700/50 overflow-hidden">
                            <Table>
                                <TableHeader className="bg-slate-800/80 sticky top-0 backdrop-blur-sm">
                                    <TableRow className="hover:bg-transparent border-slate-700/50">
                                        {Object.keys(head).map((col) => (
                                            <TableHead key={col} className="text-slate-200 uppercase text-xs font-medium tracking-wider whitespace-nowrap h-12">
                                                {col}
                                            </TableHead>
                                        ))}
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {Array.from({ length: 5 }).map((_, rowIndex) => (
                                        <TableRow key={rowIndex} className="hover:bg-slate-800/30 transition-colors border-slate-800/50">
                                            {Object.keys(head).map((col) => (
                                                <TableCell key={`${col}-${rowIndex}`} className="font-mono text-slate-400 whitespace-nowrap">
                                                    {head[col][rowIndex] !== null ? String(head[col][rowIndex]).slice(0, 30) + (String(head[col][rowIndex]).length > 30 ? '...' : '') : '-'}
                                                </TableCell>
                                            ))}
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </div>
                    </CardContent>
                </Card>
            </div>
        </div>
    );
}

