import React, { useState } from 'react'
import { api, ApiError } from '../api'

const CANONICAL_FIELDS = [
  { value: 'order_id', label: 'order_id（业务编号，必填）' },
  { value: 'customer', label: 'customer（客户，必填）' },
  { value: 'amount', label: 'amount（金额，必填）' },
  { value: 'remark', label: 'remark（备注）' },
]

/**
 * Import creation flow.
 * The workspace used here is read from props at submit time: the request is
 * stamped with whatever workspace is selected *now*. Nothing here is re-read
 * by the background worker later — the server freezes workspace and mapping
 * into the task row at creation.
 */
export default function ImportPanel({ workspaceId, onCreated }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [mapping, setMapping] = useState({})
  const [requestId, setRequestId] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)

  const reset = () => {
    setFile(null)
    setPreview(null)
    setMapping({})
    setError('')
    setInfo('')
  }

  const handleFile = async (event) => {
    const selected = event.target.files[0]
    setError('')
    setInfo('')
    if (!selected) return
    setFile(selected)
    try {
      const data = await api.preview(workspaceId, selected)
      setPreview(data)
      // Start from the server's suggested mapping; user can adjust.
      setMapping(data.suggested_mapping)
    } catch (err) {
      reset()
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  const updateMapping = (header, target) => {
    const next = { ...mapping }
    if (target === '') delete next[header]
    else next[header] = target
    setMapping(next)
  }

  const submit = async () => {
    setError('')
    setInfo('')
    if (!file) return setError('请先选择 CSV 文件')
    if (!requestId.trim()) return setError('请填写请求编号（request_id）')
    setBusy(true)
    try {
      const result = await api.createImport(workspaceId, {
        requestId: requestId.trim(),
        mapping,
        file,
      })
      setInfo(
        result.reused
          ? `请求编号已存在且文件/映射一致，已复用任务 #${result.task.id}（工作区 ${result.task.workspace_id}）`
          : `任务 #${result.task.id} 已在工作区 ${result.task.workspace_id} 创建，字段映射已固定，后台开始导入`,
      )
      onCreated?.(result.task)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && typeof err.detail === 'object') {
        setError(`${err.detail.message}（已存在任务 #${err.detail.existing_task_id}）`)
      } else {
        setError(err instanceof ApiError ? err.message : String(err))
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <h2>新建导入任务 · 当前请求将发往 <span className={`ws-chip ${workspaceId}`}>{workspaceId}</span></h2>
      {error && <div className="alert alert-error">{error}</div>}
      {info && <div className="alert alert-ok">{info}</div>}

      <label className="field">
        CSV 文件（同名文件在不同工作区互不影响）
        <input type="file" accept=".csv,text/csv" onChange={handleFile} />
      </label>

      {preview && (
        <>
          <p className="muted">
            预览 {preview.rows.length} 行（文件 {preview.filename}，表头 {preview.headers.length} 列）
          </p>
          <table>
            <thead>
              <tr>{preview.headers.map((h) => <th key={h}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => (
                <tr key={i}>
                  {preview.headers.map((h) => <td key={h}>{row[h]}</td>)}
                </tr>
              ))}
            </tbody>
          </table>

          <div className="spacer" />
          <h2>字段映射（创建后固定，后台执行不再读取页面选择）</h2>
          <table className="mapping-table">
            <thead>
              <tr><th>CSV 列</th><th>映射到标准字段</th></tr>
            </thead>
            <tbody>
              {preview.headers.map((h) => (
                <tr key={h}>
                  <td><code>{h}</code></td>
                  <td>
                    <select value={mapping[h] || ''} onChange={(e) => updateMapping(h, e.target.value)}>
                      <option value="">（不导入）</option>
                      {CANONICAL_FIELDS.map((f) => (
                        <option key={f.value} value={f.value}>{f.label}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <div className="spacer" />
          <label className="field">
            请求编号 request_id（同工作区内同编号 + 同文件 + 同映射可复用）
            <input
              type="text"
              value={requestId}
              placeholder="例如 REQ-2026-001"
              onChange={(e) => setRequestId(e.target.value)}
            />
          </label>

          <div className="row-actions">
            <button className="btn" disabled={busy} onClick={submit}>
              {busy ? '提交中…' : '创建导入任务'}
            </button>
            <button className="btn ghost" onClick={reset}>清空</button>
          </div>
        </>
      )}
    </div>
  )
}
