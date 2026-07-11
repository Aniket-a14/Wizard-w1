"use client"

import { useState, useEffect, useCallback } from "react"
import { RefreshCw, FileText, FileImage, FileSpreadsheet, Download, FileArchive, Eye, FolderOpen, Trash2, Database } from "lucide-react"
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
  const [variables, setVariables] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      // 1. Fetch Workspace Files
      const filesRes = await fetch(`${apiBaseUrl}/workspace/files`)
      if (filesRes.ok) {
        const data = await filesRes.json()
        setFiles(data.files || [])
      }

      // 2. Fetch Sandbox Variables
      const varsRes = await fetch(`${apiBaseUrl}/sandbox/variables`)
      if (varsRes.ok) {
        const varData = await varsRes.json()
        setVariables(varData || {})
      }
    } catch (e) {
      console.error("Failed to fetch workspace data:", e)
    } finally {
      setLoading(false)
    }
  }, [apiBaseUrl])

  useEffect(() => {
    fetchData()
    // Poll for changes every 6 seconds to keep it synchronized with sandbox execution
    const interval = setInterval(fetchData, 6000)
    return () => clearInterval(interval)
  }, [fetchData])

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B"
    const k = 1024
    const sizes = ["B", "KB", "MB", "GB"]
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i]
  }

  const handleDeleteFile = async (e: React.MouseEvent, file: WorkspaceFile) => {
    e.stopPropagation()
    if (!confirm(`Are you sure you want to delete '${file.name}'?`)) {
      return
    }
    try {
      const res = await fetch(`${apiBaseUrl}/data/files/${file.name}`, {
        method: "DELETE",
      })
      if (res.ok) {
        fetchData()
      } else {
        const err = await res.json()
        alert(err.detail || "Failed to delete file.")
      }
    } catch (err) {
      console.error("Failed to delete file:", err)
      alert("Network error: failed to delete file.")
    }
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

  const activeVars = Object.entries(variables)

  return (
    <div className="flex flex-col h-full bg-transparent select-none divide-y divide-stone-200/50">
      {/* SECTION: FILES */}
      <div className="flex flex-col flex-1 min-h-[50%] overflow-hidden">
        <div className="flex items-center justify-between px-5 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-400">Workspace Files</h3>
          <Button
            onClick={fetchData}
            variant="ghost"
            size="icon"
            className="w-7 h-7 hover:bg-stone-200/60 text-stone-400 hover:text-stone-600 rounded-lg"
            disabled={loading}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>

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
                  {file.name !== "dataset.csv" && file.name !== "dataset.feather" && (
                    <Button
                      onClick={(e) => handleDeleteFile(e, file)}
                      variant="ghost"
                      size="icon"
                      className="w-7 h-7 hover:bg-rose-50 hover:text-rose-600 rounded-lg text-stone-400"
                      title="Delete File"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </Button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* SECTION: VARIABLE INSPECTOR */}
      <div className="flex flex-col flex-1 min-h-[40%] overflow-hidden bg-stone-50/30">
        <div className="flex items-center justify-between px-5 py-3">
          <div className="flex items-center gap-1.5">
            <Database className="w-3.5 h-3.5 text-stone-400" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-400">Sandbox Memory</h3>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-4 space-y-1.5">
          {activeVars.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-36 text-center px-6">
              <p className="text-[11px] text-stone-400">No active variables in memory</p>
              <p className="text-[10px] mt-1 text-stone-400/70 leading-relaxed">Run a code execution block to allocate variables.</p>
            </div>
          ) : (
            activeVars.map(([varName, info]: [string, any]) => (
              <div
                key={varName}
                className="flex flex-col p-2 rounded-xl bg-white border border-stone-200/50 shadow-xs"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono font-bold text-stone-800">{varName}</span>
                  <span className="text-[10px] font-medium text-stone-400 bg-stone-100 px-1.5 py-0.5 rounded-md">
                    {info.type}
                  </span>
                </div>
                {info.shape && (
                  <div className="text-[10px] text-emerald-600 font-medium mt-0.5">
                    Shape: {Array.isArray(info.shape) ? `(${info.shape.join(", ")})` : info.shape}
                  </div>
                )}
                {info.preview && (
                  <div className="text-[10px] text-stone-400/80 font-mono mt-1 break-all truncate leading-relaxed">
                    {info.preview}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
