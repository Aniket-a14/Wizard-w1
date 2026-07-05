"use client"

import { useState, useEffect, useCallback } from "react"
import { RefreshCw, FileText, FileImage, FileSpreadsheet, Download, FileArchive, Eye, FolderOpen } from "lucide-react"
import { Button } from "./ui/button"

export interface WorkspaceFile {
  name: string
  path: string
  size: number
  type: "image" | "csv" | "text" | "binary" | "file"
}

interface WorkspaceExplorerProps {
  apiBaseUrl: string
  onSelectCsv: (path: string) => void
  onSelectImage: (url: string) => void
}

export function WorkspaceExplorer({ apiBaseUrl, onSelectCsv, onSelectImage }: WorkspaceExplorerProps) {
  const [files, setFiles] = useState<WorkspaceFile[]>([])
  const [loading, setLoading] = useState(false)

  const fetchFiles = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${apiBaseUrl}/workspace/files`)
      if (res.ok) {
        const data = await res.json()
        setFiles(data.files || [])
      }
    } catch (e) {
      console.error("Failed to fetch workspace files:", e)
    } finally {
      setLoading(false)
    }
  }, [apiBaseUrl])

  useEffect(() => {
    fetchFiles()
    // Poll for changes every 6 seconds to keep it synchronized with sandbox execution
    const interval = setInterval(fetchFiles, 6000)
    return () => clearInterval(interval)
  }, [fetchFiles])

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B"
    const k = 1024
    const sizes = ["B", "KB", "MB", "GB"]
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i]
  }

  const getIcon = (type: string) => {
    switch (type) {
      case "image":
        return <FileImage className="w-4 h-4 text-rose-500" />
      case "csv":
        return <FileSpreadsheet className="w-4 h-4 text-emerald-600" />
      case "text":
        return <FileText className="w-4 h-4 text-blue-500" />
      case "binary":
        return <FileArchive className="w-4 h-4 text-amber-500" />
      default:
        return <FileText className="w-4 h-4 text-stone-400" />
    }
  }

  const getBgTint = (type: string) => {
    switch (type) {
      case "image":
        return "bg-rose-50/60"
      case "csv":
        return "bg-emerald-50/60"
      case "text":
        return "bg-blue-50/60"
      case "binary":
        return "bg-amber-50/60"
      default:
        return "bg-stone-50/60"
    }
  }

  const handlePreview = (file: WorkspaceFile) => {
    const fileUrl = `${apiBaseUrl}/workspace/static/${file.path}`
    if (file.type === "csv") {
      onSelectCsv(file.path)
    } else if (file.type === "image") {
      onSelectImage(fileUrl)
    }
  }

  return (
    <div className="flex flex-col h-full bg-transparent select-none">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-400">Workspace</h3>
        <Button
          onClick={fetchFiles}
          variant="ghost"
          size="icon"
          className="w-7 h-7 hover:bg-stone-200/60 text-stone-400 hover:text-stone-600 rounded-lg"
          disabled={loading}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </div>

      {/* File list */}
      <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-1">
        {files.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-center px-6">
            <div className="w-14 h-14 rounded-2xl bg-stone-100 flex items-center justify-center mb-3">
              <FolderOpen className="w-6 h-6 text-stone-300" />
            </div>
            <p className="text-xs font-medium text-stone-400">No files yet</p>
            <p className="text-[11px] mt-1 text-stone-400/70 leading-relaxed">Upload a dataset or run analysis to populate your workspace.</p>
          </div>
        ) : (
          files.map((file) => (
            <div
              key={file.path}
              className="group flex items-center justify-between p-2.5 rounded-xl hover:bg-white cursor-pointer transition-all duration-150 border border-transparent hover:border-stone-200/60 hover:shadow-sm"
              onClick={() => handlePreview(file)}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div className={`w-8 h-8 rounded-lg ${getBgTint(file.type)} flex items-center justify-center shrink-0`}>
                  {getIcon(file.type)}
                </div>
                <div className="min-w-0">
                  <p className="text-xs font-medium truncate text-stone-700 group-hover:text-stone-900 transition-colors">
                    {file.name}
                  </p>
                  <p className="text-[10px] text-stone-400">{formatSize(file.size)}</p>
                </div>
              </div>

              <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                {(file.type === "csv" || file.type === "image") && (
                  <Button
                    onClick={(e) => {
                      e.stopPropagation()
                      handlePreview(file)
                    }}
                    variant="ghost"
                    size="icon"
                    className="w-7 h-7 hover:bg-stone-100 hover:text-stone-700 rounded-lg text-stone-400"
                    title="Preview File"
                  >
                    <Eye className="w-3.5 h-3.5" />
                  </Button>
                )}
                <a
                  href={`${apiBaseUrl}/workspace/static/${file.path}`}
                  download={file.name}
                  onClick={(e) => e.stopPropagation()}
                  className="flex items-center justify-center w-7 h-7 hover:bg-stone-100 hover:text-stone-700 rounded-lg text-stone-400 transition-colors"
                  title="Download File"
                >
                  <Download className="w-3.5 h-3.5" />
                </a>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
