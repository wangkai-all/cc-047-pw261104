import React from 'react'

const STATUS_LABEL = {
  pending: '等待中',
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export function StatusBadge({ status }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status] || status}</span>
}

export function progressPercent(task) {
  if (!task.total_rows) return 0
  return Math.round((task.processed_rows / task.total_rows) * 100)
}

export default function TaskList({ tasks, workspaceId, onOpen }) {
  if (!tasks.length) {
    return <p className="muted">当前工作区暂无导入任务。另一个工作区的任务不会出现在这里。</p>
  }
  return (
    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>所属工作区</th>
          <th>请求编号</th>
          <th>文件名</th>
          <th>状态</th>
          <th>进度</th>
          <th>成功/失败</th>
          <th>创建时间</th>
        </tr>
      </thead>
      <tbody>
        {tasks.map((t) => (
          <tr key={t.id} className="clickable" onClick={() => onOpen(t.id)}>
            <td className="mono">#{t.id}</td>
            <td><span className={`ws-chip ${t.workspace_id}`}>{t.workspace_id}</span></td>
            <td className="mono">{t.request_id}</td>
            <td>{t.filename}</td>
            <td><StatusBadge status={t.status} /></td>
            <td>
              <div className="progress">
                <span style={{ width: `${progressPercent(t)}%` }} />
              </div>
              <span className="muted mono">{t.processed_rows}/{t.total_rows}</span>
            </td>
            <td>
              <span style={{ color: 'var(--ok)' }}>{t.success_rows}</span>
              {' / '}
              <span style={{ color: t.failed_rows ? 'var(--danger)' : undefined }}>{t.failed_rows}</span>
            </td>
            <td className="mono">{t.created_at}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
