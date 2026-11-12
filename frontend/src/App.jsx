import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, getStoredWorkspaceId, setStoredWorkspaceId } from './api'
import WorkspaceSwitcher from './components/WorkspaceSwitcher'
import ImportPanel from './components/ImportPanel'
import TaskList from './components/TaskList'
import TaskDetail from './components/TaskDetail'
import RecordsView from './components/RecordsView'

export default function App() {
  const [workspaces, setWorkspaces] = useState([])
  const [workspaceId, setWorkspaceId] = useState(null)
  const [tasks, setTasks] = useState([])
  const [view, setView] = useState('imports') // imports | records
  const [openTaskId, setOpenTaskId] = useState(null)
  const [loadError, setLoadError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => {
    api.workspaces().then((ws) => {
      setWorkspaces(ws)
      const stored = getStoredWorkspaceId()
      const initial = ws.find((w) => w.id === stored) ? stored : ws[0].id
      setWorkspaceId(initial)
    })
  }, [])

  const loadTasks = useCallback(async () => {
    if (!workspaceId) return
    try {
      const data = await api.listImports(workspaceId)
      setTasks(data.items)
      setLoadError('')
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : String(err))
    }
  }, [workspaceId])

  useEffect(() => {
    loadTasks()
  }, [loadTasks])

  // Poll only while at least one task in the CURRENT workspace is active.
  useEffect(() => {
    const anyRunning = tasks.some((t) => ['pending', 'running'].includes(t.status))
    if (anyRunning) {
      pollRef.current = setInterval(loadTasks, 1000)
      return () => clearInterval(pollRef.current)
    }
  }, [tasks, loadTasks])

  const switchWorkspace = (id) => {
    if (id === workspaceId) return
    setStoredWorkspaceId(id)
    setWorkspaceId(id)
    // Detail view stays open on purpose: its refetch with the new header
    // demonstrates the cross-workspace 404. Switching does not cancel or
    // re-scope any task created earlier — the server holds that binding.
    setView('imports')
  }

  if (!workspaceId) return <div className="app">加载中…</div>

  const currentWs = workspaces.find((w) => w.id === workspaceId)

  return (
    <div className="app">
      <div className="topbar">
        <div>
          <h1>多工作区 CSV 导入演示</h1>
          <span className="account-badge">本地演示账号 demo-account · 可访问 2 个工作区 · 每个请求显式携带 X-Workspace-Id</span>
        </div>
        <WorkspaceSwitcher
          workspaces={workspaces}
          currentId={workspaceId}
          onChange={switchWorkspace}
        />
      </div>

      <p className="ws-note">
        当前工作区：<b>{currentWs?.name}</b>（{workspaceId}）。切换只影响之后发起的请求；
        已创建的任务在后台继续按创建时绑定的工作区与映射执行。
      </p>

      {openTaskId ? (
        <TaskDetail
          taskId={openTaskId}
          workspaceId={workspaceId}
          onBack={() => setOpenTaskId(null)}
        />
      ) : (
        <>
          <div className="tabs">
            <button className={`tab ${view === 'imports' ? 'active' : ''}`} onClick={() => setView('imports')}>
              导入与任务
            </button>
            <button className={`tab ${view === 'records' ? 'active' : ''}`} onClick={() => setView('records')}>
              已导入记录
            </button>
          </div>

          {view === 'imports' && (
            <>
              <ImportPanel workspaceId={workspaceId} onCreated={loadTasks} />
              <div className="panel">
                <h2>本工作区的导入任务</h2>
                {loadError && <div className="alert alert-error">{loadError}</div>}
                <TaskList tasks={tasks} workspaceId={workspaceId} onOpen={setOpenTaskId} />
              </div>
            </>
          )}

          {view === 'records' && <RecordsView workspaceId={workspaceId} />}
        </>
      )}
    </div>
  )
}
