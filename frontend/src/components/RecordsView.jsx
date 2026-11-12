import React, { useEffect, useState } from 'react'
import { api, ApiError } from '../api'

/**
 * Imported records for the CURRENT workspace. Filtering by business key makes
 * the "overlapping primary key" story easy to verify row by row: the same
 * ORD-1001 shows Alpha's payload in ws-alpha and Beta's in ws-beta.
 */
export default function RecordsView({ workspaceId }) {
  const [data, setData] = useState({ items: [], total: 0 })
  const [keyFilter, setKeyFilter] = useState('')
  const [error, setError] = useState('')

  const load = async (key = keyFilter) => {
    setError('')
    try {
      setData(await api.listRecords(workspaceId, key.trim() || undefined))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
    }
  }

  useEffect(() => {
    setKeyFilter('')
    load('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId])

  return (
    <div className="panel">
      <h2>已导入记录 · 工作区 <span className={`ws-chip ${workspaceId}`}>{workspaceId}</span></h2>
      {error && <div className="alert alert-error">{error}</div>}
      <div style={{ display: 'flex', gap: '8px', marginBottom: 12 }}>
        <input
          type="text"
          style={{ maxWidth: 280 }}
          placeholder="按业务编号过滤，例如 ORD-1001"
          value={keyFilter}
          onChange={(e) => setKeyFilter(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
        />
        <button className="btn small" onClick={() => load()}>查询</button>
        <button className="btn small ghost" onClick={() => { setKeyFilter(''); load('') }}>重置</button>
      </div>
      <p className="muted">共 {data.total} 条（仅当前工作区；重叠主键在另一工作区是独立的一行）</p>
      <table>
        <thead>
          <tr>
            <th>业务编号</th>
            <th>所属工作区</th>
            <th>来源任务</th>
            <th>CSV 行号</th>
            <th>客户</th>
            <th>金额</th>
            <th>备注</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((r) => (
            <tr key={`${r.workspace_id}-${r.business_key}`}>
              <td className="mono">{r.business_key}</td>
              <td><span className={`ws-chip ${r.workspace_id}`}>{r.workspace_id}</span></td>
              <td className="mono">#{r.task_id}</td>
              <td>{r.row_number}</td>
              <td>{r.payload.customer}</td>
              <td>{r.payload.amount}</td>
              <td>{r.payload.remark}</td>
            </tr>
          ))}
          {!data.items.length && (
            <tr><td colSpan={7} className="muted">无记录</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}
