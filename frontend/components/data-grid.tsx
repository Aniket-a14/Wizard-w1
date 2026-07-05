"use client"

import { useState, useEffect, useCallback } from "react"
import { ArrowUp, ArrowDown, ChevronLeft, ChevronRight, Table2, Database } from "lucide-react"

interface DataGridProps {
  apiBaseUrl: string
  csvPath: string | null
}

export function DataGrid({ apiBaseUrl, csvPath }: DataGridProps) {
  const [data, setData] = useState<any[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [page, setPage] = useState(1)
  const [perPage] = useState(50)
  const [totalRows, setTotalRows] = useState(0)
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc")
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      let url = `${apiBaseUrl}/data/preview?page=${page}&per_page=${perPage}`
      if (sortBy) {
        url += `&sort_by=${encodeURIComponent(sortBy)}&sort_order=${sortOrder}`
      }
      
      const res = await fetch(url)
      if (res.ok) {
        const result = await res.json()
        setData(result.data || [])
        setColumns(result.columns || [])
        setTotalRows(result.total_rows || 0)
      }
    } catch (e) {
      console.error("Failed to fetch data grid preview:", e)
    } finally {
      setLoading(false)
    }
  }, [apiBaseUrl, page, perPage, sortBy, sortOrder])

  useEffect(() => {
    fetchData()
  }, [fetchData, csvPath]) // Trigger reload if a new CSV file is selected

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"))
    } else {
      setSortBy(column)
      setSortOrder("asc")
    }
    setPage(1) // Reset to first page when sorting changes
  }

  const totalPages = Math.ceil(totalRows / perPage)

  return (
    <div className="flex flex-col h-full bg-white text-stone-700">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-stone-200/60 grid-header">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-emerald-50 flex items-center justify-center">
            <Table2 className="w-3.5 h-3.5 text-emerald-600" />
          </div>
          <div>
            <h3 className="text-xs font-semibold text-stone-700">
              {csvPath ? csvPath.split("/").pop() : "Dataset Preview"}
            </h3>
            {totalRows > 0 && (
              <p className="text-[10px] text-stone-400 mt-0.5">
                Showing {(page - 1) * perPage + 1}–{Math.min(page * perPage, totalRows)} of {totalRows.toLocaleString()} rows
              </p>
            )}
          </div>
        </div>
        {totalRows > 0 && (
          <span className="text-[10px] font-medium text-stone-400 bg-stone-100 px-2 py-0.5 rounded-full">
            {columns.length} cols
          </span>
        )}
      </div>

      {/* Grid Container */}
      <div className="flex-1 overflow-auto relative">
        {loading && (
          <div className="absolute inset-0 bg-white/70 backdrop-blur-[2px] flex items-center justify-center z-10 transition-opacity">
            <div className="w-5 h-5 border-2 border-stone-300 border-t-stone-700 rounded-full animate-spin" />
          </div>
        )}

        {totalRows === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center px-6">
            <div className="w-14 h-14 rounded-2xl bg-stone-50 flex items-center justify-center mb-3">
              <Database className="w-6 h-6 text-stone-200" />
            </div>
            <p className="text-xs font-medium text-stone-400">No dataset loaded</p>
            <p className="text-[11px] text-stone-400/70 mt-1 leading-relaxed max-w-[220px]">Upload a CSV file to inspect and explore your data here.</p>
          </div>
        ) : (
          <table className="w-full text-left border-collapse text-xs select-text">
            <thead className="grid-header sticky top-0 border-b border-stone-200/60 z-10 select-none">
              <tr>
                {columns.map((col) => (
                  <th
                    key={col}
                    onClick={() => handleSort(col)}
                    className="px-4 py-2.5 font-semibold text-stone-500 hover:text-stone-700 hover:bg-stone-100/60 cursor-pointer select-none transition-colors border-r border-stone-100 last:border-r-0 text-[11px] uppercase tracking-wide"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate">{col}</span>
                      {sortBy === col ? (
                        sortOrder === "asc" ? (
                          <ArrowUp className="w-3 h-3 text-emerald-600 shrink-0" />
                        ) : (
                          <ArrowDown className="w-3 h-3 text-emerald-600 shrink-0" />
                        )
                      ) : null}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, index) => (
                <tr
                  key={index}
                  className={`transition-colors hover:bg-emerald-50/30 ${index % 2 === 0 ? "bg-white" : "bg-stone-50/40"}`}
                >
                  {columns.map((col) => (
                    <td
                      key={`${index}-${col}`}
                      className="px-4 py-2 border-r border-stone-100/60 last:border-r-0 text-stone-600 font-mono text-[11px] truncate max-w-[200px]"
                      title={row[col] !== null ? String(row[col]) : ""}
                    >
                      {row[col] !== null && row[col] !== undefined ? String(row[col]) : <span className="text-stone-300 italic">null</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-5 py-2.5 border-t border-stone-100 bg-white select-none">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 text-[11px] font-medium text-stone-500 hover:text-stone-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors px-2.5 py-1.5 rounded-lg hover:bg-stone-50"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            Prev
          </button>

          <div className="flex items-center gap-1">
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              let pageNum: number
              if (totalPages <= 5) {
                pageNum = i + 1
              } else if (page <= 3) {
                pageNum = i + 1
              } else if (page >= totalPages - 2) {
                pageNum = totalPages - 4 + i
              } else {
                pageNum = page - 2 + i
              }
              return (
                <button
                  key={pageNum}
                  onClick={() => setPage(pageNum)}
                  className={`w-7 h-7 rounded-md text-[11px] font-medium transition-all duration-150 ${
                    page === pageNum
                      ? "bg-stone-900 text-white shadow-sm"
                      : "text-stone-400 hover:text-stone-600 hover:bg-stone-100"
                  }`}
                >
                  {pageNum}
                </button>
              )
            })}
          </div>

          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="flex items-center gap-1 text-[11px] font-medium text-stone-500 hover:text-stone-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors px-2.5 py-1.5 rounded-lg hover:bg-stone-50"
          >
            Next
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  )
}
