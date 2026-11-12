import React from 'react'

export default function WorkspaceSwitcher({ workspaces, currentId, onChange }) {
  return (
    <div className="ws-tabs" role="tablist" aria-label="工作区切换">
      {workspaces.map((ws) => (
        <button
          key={ws.id}
          role="tab"
          aria-selected={ws.id === currentId}
          className={`ws-tab ${ws.id === currentId ? `active-${ws.id}` : ''}`}
          onClick={() => onChange(ws.id)}
        >
          {ws.name}
          <span className="mono">（{ws.id}）</span>
        </button>
      ))}
    </div>
  )
}
