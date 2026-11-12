import React, { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api'
import { StatusBadge, progressPercent } from './TaskList'

/**
 * Task detail.
 * The task row is always fetched WITH the currently selected workspace header.
 * If the user switches workspace while a task runs, opening the same numeric
 * id from the other workspace returns 404 — exactly what this view surfaces.
 * The running worker itself is unaffected: it was bound to its workspace at
 * creation time and never reads this UI selection.
 */
export default function TaskDetail({ taskId, workspaceId, onBack }) {
  const [task, setTask] = useState(null)
  const [notFound, setNotFound] = useState('')
  const [error, setError] = useState('')
  const timer = useRef(null)

  const load = React.useCallback(async () => {
    try {
      const data = await api.getImport(workspaceId, taskId)
      setTask(data)
      setNotFound('')
      return data.status
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(err.message)
        setTask(null)
        return 'not-found'
      }
      setError(err instanceof ApiError ? err.message : String(err))
      return 'error'
    }
  }, [workspaceId, taskId])

  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      const status = await load()
      if (cancelled) return
      if (status === 'running' || status === 'pending') {
        timer.current = setTimeout(tick, 800)
      }
    }
    tick()
    return () => {
      cancelled = true
      if (timer.current) clearTimeout(timer.current)
    }
  }, [load])

  const cancel = async () => {
    setError('')
    try {
      await api.cancelImport(workspaceId, taskId)
      load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  const remove = async () => {
    if (!window.confirm('确认清理该任务及其全部文件和已导入记录？仅影响本工作区的本任务。')) return
    setError('')
    try {
      await api.deleteImport(workspaceId, taskId)
      onBack()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  const download = async (path, fallbackName) => {
    try {
      const url = await api.downloadUrl(workspaceId, path)
      const a = document.createElement('a')
      a.href = url
      a.download = fallbackName
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  if (notFound) {
    return (
      <div className="panel">
        <span className="back-link" onClick={onBack}>← 返回任务列表</span>
        <div className="alert alert-error">
          404：{notFound}
          <div className="spacer" />
          <span className="muted">
            这通常说明该批次编号属于另一个工作区。工作区隔离下，跨工作区引用一律返回“找不到”，
            而不是返回对方的数据。正在后台执行的原任务不受影响。
          </span>
        </div>
      </div>
    )
  }

  if (!task) return <div className="panel">{error ? <div className="alert alert-error">{error}</div> : '加载中…'}</div>

  const running = task.status === 'running' || task.status === 'pending'

  return (
    <div className="panel">
      <span className="back-link" onClick={onBack}>← 返回任务列表</span>
      <h2>任务 #{task.id} 详情</h2>
      {error && <div className="alert alert-error">{error}</div>}

      <dl className="kv">
        <dt>任务创建时所属工作区</dt>
        <dd><span className={`ws-chip ${task.workspace_id}`}>{task.workspace_id}</span>（创建后固定，不随页面切换改变）</dd>

        <dt>当前页面工作区</dt>
        <dd><span className={`ws-chip ${workspaceId}`}>{workspaceId}</span>{task.workspace_id !== workspaceId && <b style={{ color: 'var(--danger)' }}> · 与任务归属不一致 → 服务端应返回 404</b>}</dd>

        <dt>请求编号</dt><dd className="mono">{task.request_id}</dd>
        <dt>文件名</dt><dd>{task.filename}</dd>
        <dt>状态</dt><dd><StatusBadge status={task.status} /> {running && <span className="muted">（后台执行中，切换工作区不会中断它）</span>}</dd>
        <dt>进度</dt>
        <dd>
          <div className="progress"><span style={{ width: `${progressPercent(task)}%` }} /></div>
          <span className="mono muted">{task.processed_rows}/{task.total_rows} 行 · 成功 {task.success_rows} · 失败 {task.failed_rows}</span>
        </dd>
        <dt>文件哈希</dt><dd className="mono">{task.file_hash.slice(0, 24)}…</dd>
        <dt>错误信息</dt><dd>{task.error_message || <span className="muted">无</span>}</dd>
        <dt>创建 / 更新时间</dt><dd className="mono">{task.created_at} / {task.updated_at}</dd>
      </dl>

      <div className="spacer" />
      <h2>创建时固定的字段映射</h2>
      <table className="mapping-table">
        <thead><tr><th>CSV 列</th><th>标准字段</th></tr></thead>
        <tbody>
          {Object.entries(task.mapping).map(([src, target]) => (
            <tr key={src}><td><code>{src}</code></td><td><code>{target}</code></td></tr>
          ))}
        </tbody>
      </table>

      <div className="row-actions">
        {running && <button className="btn danger" onClick={cancel}>取消任务（仅本任务）</button>}
        {!running && <button className="btn danger ghost" onClick={remove}>清理任务与文件</button>}
        <button className="btn ghost" onClick={() => download(`/api/imports/${task.id}/download`, `${task.workspace_id}_${task.filename}`)}>
          下载原始 CSV
        </button>
        {task.has_error_file && (
          <button className="btn ghost" onClick={() => download(`/api/imports/${task.id}/errors`, `${task.workspace_id}_task${task.id}_errors.csv`)}>
            下载错误行文件
          </button>
        )}
      </div>
    </div>
  )
}
