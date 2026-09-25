import { useEffect, useMemo, useState } from 'react'
import Icon from './Icon.jsx'

// Generic grid with paging (default 5 rows per page).
// columns: [{ key, header, render(row), className, width }]
export default function DataGrid({ columns, rows, rowKey, pageSize = 5, empty, rowClassName, toolbar, page: controlledPage, onPageChange }) {
  const [innerPage, setInnerPage] = useState(1)
  const page = controlledPage ?? innerPage
  const setPage = onPageChange ?? setInnerPage
  const pages = Math.max(1, Math.ceil(rows.length / pageSize))
  useEffect(() => { if (page > pages) setPage(pages) }, [page, pages, setPage])
  const visible = useMemo(() => rows.slice((page - 1) * pageSize, page * pageSize), [rows, page, pageSize])
  const from = rows.length ? (page - 1) * pageSize + 1 : 0
  const to = Math.min(page * pageSize, rows.length)

  const pageButtons = []
  const windowStart = Math.max(1, Math.min(page - 2, pages - 4))
  for (let p = windowStart; p <= Math.min(pages, windowStart + 4); p++) pageButtons.push(p)

  return (
    <div className="card">
      {toolbar && <div className="grid-toolbar">{toolbar}</div>}
      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>{columns.map((c) => <th key={c.key} className={c.className} style={c.width ? { width: c.width } : undefined}>{c.header}</th>)}</tr>
          </thead>
          <tbody>
            {visible.map((row) => (
              <tr key={rowKey(row)} className={rowClassName?.(row) || ''}>
                {columns.map((c) => <td key={c.key} className={c.className}>{c.render ? c.render(row) : row[c.key]}</td>)}
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={columns.length} className="grid-empty">{empty || 'Nothing here yet.'}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span className="muted small">Showing {from}–{to} of {rows.length}</span>
        <div className="pager-pages">
          <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage(page - 1)}><Icon name="chevronLeft" size={15} />Prev</button>
          {pageButtons.map((p) => (
            <button key={p} className={`btn btn-sm ${p === page ? 'current' : ''}`} onClick={() => setPage(p)} aria-current={p === page ? 'page' : undefined}>{p}</button>
          ))}
          <button className="btn btn-sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next<Icon name="chevronRight" size={15} /></button>
        </div>
      </div>
    </div>
  )
}
