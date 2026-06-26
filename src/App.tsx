import { useState, useRef, useEffect, type DragEvent, type ChangeEvent } from 'react'
import { useAuth } from './AuthContext'
import TopBar from './TopBar'

type RowStatus = 'new' | 'duplicate' | 'needs_manual'

interface PreviewRow {
  date_short: string
  amount_fmt: string
  raw_name: string
  expense_name: string
  category: string
  status: RowStatus
}

interface SheetRefundWarning {
  credit_date: string
  credit_name: string
  credit_amount: string
  sheet_date: string
  sheet_amount: string
}

interface MonthPreview {
  sheet_name: string
  month: number
  start_col: string
  insert_row: number
  categories: string[]
  rows: PreviewRow[]
  sheet_refund_warnings: SheetRefundWarning[]
  error?: string
}

interface RefundPair {
  debit_date: string
  debit_name: string
  credit_date: string
  credit_name: string
  amount: string
}

interface PreviewResponse {
  previews: MonthPreview[]
  refunds_paired: RefundPair[]
}

interface CommitResponse {
  total_added: number
  results: { sheet_name: string; month: number; added: number }[]
}

function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
}

const MONTH_NAMES = [
  '', 'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

const API_URL = import.meta.env.VITE_API_BASE || ''
const PENDING_CSV_KEY = 'pending_csv'

interface SavedCsv {
  name: string
  content: string
}

function fileFromSaved(saved: SavedCsv): File {
  return new File([saved.content], saved.name, { type: 'text/csv' })
}

export default function App() {
  const { isAuthenticated, signIn, isLoading: authLoading } = useAuth()
  const [file, setFile] = useState<File | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [previews, setPreviews] = useState<MonthPreview[] | null>(null)
  const [refundsPaired, setRefundsPaired] = useState<RefundPair[]>([])
  const [unpairedCredits, setUnpairedCredits] = useState<RefundPair[]>([])
  const [expandedDupes, setExpandedDupes] = useState<Record<string, boolean>>({})
  const [committing, setCommitting] = useState(false)
  const [result, setResult] = useState<CommitResponse | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = (f: File) => {
    if (!f.name.endsWith('.csv')) {
      setError('Please upload a CSV file')
      return
    }
    setError(null)
    setFile(f)
    setPreviews(null)
    setResult(null)
    f.text().then(content => {
      sessionStorage.setItem(PENDING_CSV_KEY, JSON.stringify({ name: f.name, content }))
    }).catch(() => {})
  }

  useEffect(() => {
    const saved = sessionStorage.getItem(PENDING_CSV_KEY)
    if (!saved) return
    try {
      const parsed: SavedCsv = JSON.parse(saved)
      setFile(fileFromSaved(parsed))
    } catch {
      sessionStorage.removeItem(PENDING_CSV_KEY)
    }
  }, [])

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragActive(false)
    if (e.dataTransfer.files?.[0]) handleFile(e.dataTransfer.files[0])
  }

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.[0]) handleFile(e.target.files[0])
  }

  const clear = () => {
    setFile(null)
    setPreviews(null)
    setError(null)
    setResult(null)
    sessionStorage.removeItem(PENDING_CSV_KEY)
    if (inputRef.current) inputRef.current.value = ''
  }

  const fetchPreview = async () => {
    if (!file) return
    if (!isAuthenticated) {
      setError('Please sign in with Google to import transactions')
      signIn()
      return
    }

    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(`${API_URL}/api/import/preview`, {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Preview failed')
      }
      const data: PreviewResponse = await res.json()
      setPreviews(data.previews)
      setRefundsPaired(data.refunds_paired || [])
      setUnpairedCredits([])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed')
    } finally {
      setLoading(false)
    }
  }

  const updateRow = (monthIdx: number, rowIdx: number, patch: Partial<PreviewRow>) => {
    if (!previews) return
    const next = previews.map((p, mi) =>
      mi !== monthIdx ? p : {
        ...p,
        rows: p.rows.map((r, ri) => ri !== rowIdx ? r : { ...r, ...patch }),
      },
    )
    setPreviews(next)
  }

  const unpairRefund = (pairIdx: number) => {
    if (!previews) return
    const pair = refundsPaired[pairIdx]
    const year = parseInt(pair.debit_date.slice(0, 4))
    const month = parseInt(pair.debit_date.slice(5, 7))
    const day = parseInt(pair.debit_date.slice(8, 10))
    const next = previews.map(p => {
      if (p.sheet_name !== String(year) || p.month !== month) return p
      const restored: PreviewRow = {
        date_short: `${month}/${day}`,
        amount_fmt: pair.amount,
        raw_name: pair.debit_name,
        expense_name: '',
        category: 'NEED MANUAL ENTRY',
        status: 'needs_manual',
      }
      // Insert in ascending date_short order so sheet writes stay chronological.
      const key = (d: string) => {
        const [m, dd] = d.split('/').map(Number)
        return m * 100 + dd
      }
      const restoredKey = key(restored.date_short)
      const idx = p.rows.findIndex(r => key(r.date_short) > restoredKey)
      const insertAt = idx === -1 ? p.rows.length : idx
      const rows = [...p.rows.slice(0, insertAt), restored, ...p.rows.slice(insertAt)]
      return { ...p, rows }
    })
    setPreviews(next)
    setRefundsPaired(rp => rp.filter((_, i) => i !== pairIdx))
    setUnpairedCredits(uc => [...uc, pair])
  }

  const toggleSkip = (monthIdx: number, rowIdx: number) => {
    if (!previews) return
    const row = previews[monthIdx].rows[rowIdx]
    const nextStatus: RowStatus =
      row.status === 'duplicate' ? 'new' :
      row.status === 'new' || row.status === 'needs_manual' ? 'duplicate' :
      row.status
    updateRow(monthIdx, rowIdx, { status: nextStatus })
  }

  const commit = async () => {
    if (!previews) return
    setCommitting(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/import/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ previews }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Commit failed')
      }
      const data: CommitResponse = await res.json()
      setResult(data)
      setPreviews(null)
      sessionStorage.removeItem(PENDING_CSV_KEY)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Commit failed')
    } finally {
      setCommitting(false)
    }
  }

  if (authLoading) {
    return (
      <div className="app">
        <TopBar />
        <div className="loading-screen">Loading...</div>
      </div>
    )
  }

  const totalToCommit = previews
    ? previews.reduce((n, p) => n + p.rows.filter(r => r.status !== 'duplicate').length, 0)
    : 0

  return (
    <div className="app">
      <TopBar />
      <header className="header">
        <h1>Transaction Importer</h1>
        <p>Upload your statement to categorize transactions</p>
      </header>

      <div className="upload-card">
        <div
          className={`dropzone ${dragActive ? 'active' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true) }}
          onDragLeave={() => setDragActive(false)}
        >
          <svg className="dropzone-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 16V4m0 0l-4 4m4-4l4 4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
          </svg>
          <div className="dropzone-text">Drop CSV file or click to browse</div>
          <div className="dropzone-hint">Supports Elan Financial Services only</div>
        </div>

        <input ref={inputRef} type="file" accept=".csv" onChange={onChange} hidden />

        {error && <div className="error-msg">{error}</div>}

        {file && !error && (
          <div className="file-badge">
            <div className="file-info">
              <span className="file-icon">📄</span>
              <div>
                <div className="file-name">{file.name}</div>
                <div className="file-size">{formatSize(file.size)}</div>
              </div>
            </div>
            <button className="file-remove" onClick={clear}>×</button>
          </div>
        )}

        {!previews && !result && (
          <button
            className="submit-btn"
            disabled={!file || loading}
            onClick={fetchPreview}
          >
            {loading ? 'Classifying with Claude...' : 'Preview Import'}
          </button>
        )}

        {result && (
          <div className="success-msg">
            <strong>Import Complete</strong>
            <p>{result.total_added} transactions added</p>
          </div>
        )}
      </div>

      {previews && refundsPaired.length > 0 && (
        <section className="preview">
          <div className="preview-header">
            <span className="preview-title">Refunds detected (skipped)</span>
            <span className="preview-count">{refundsPaired.length} pair{refundsPaired.length === 1 ? '' : 's'}</span>
          </div>
          <div className="preview-table">
            <table>
              <thead>
                <tr>
                  <th>Amount</th>
                  <th>Debit</th>
                  <th>Credit</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {refundsPaired.map((r, i) => (
                  <tr key={i}>
                    <td className="amount">{r.amount}</td>
                    <td style={{ fontSize: 12 }}>{r.debit_date} · {r.debit_name}</td>
                    <td style={{ fontSize: 12 }}>{r.credit_date} · {r.credit_name}</td>
                    <td>
                      <button
                        type="button"
                        onClick={() => unpairRefund(i)}
                        style={{
                          border: '1px solid var(--border)', background: 'var(--card)',
                          padding: '4px 10px', borderRadius: 4, cursor: 'pointer', fontSize: 12,
                        }}
                      >
                        Un-pair
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {previews && unpairedCredits.length > 0 && (
        <section className="preview">
          <div className="preview-header">
            <span className="preview-title">Un-paired credits — verify manually</span>
            <span className="preview-count">{unpairedCredits.length}</span>
          </div>
          <div
            style={{
              background: '#fffbeb',
              border: '1px solid #fbbf24',
              borderRadius: 8,
              padding: '12px 16px',
              fontSize: 13,
            }}
          >
            <p style={{ color: 'var(--text-muted)', marginBottom: 8 }}>
              These credits were originally paired as refunds. Check your sheet to confirm
              they don't refund an already-imported row, then remove that row from the sheet
              if they do.
            </p>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {unpairedCredits.map((c, i) => (
                <li key={i}>
                  {c.credit_date} · {c.amount} · {c.credit_name}
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {previews && previews.map((p, mi) => {
        const key = `${p.sheet_name}-${p.month}`
        const dupeCount = p.rows.filter(r => r.status === 'duplicate').length
        const importCount = p.rows.filter(r => r.status !== 'duplicate').length
        const showDupes = !!expandedDupes[key]
        const visibleRows = showDupes ? p.rows : p.rows.filter(r => r.status !== 'duplicate')
        return (
        <section className="preview" key={key}>
          <div className="preview-header">
            <span className="preview-title">
              {MONTH_NAMES[p.month]} {p.sheet_name}
            </span>
            <span className="preview-count">
              {importCount} to import
              {dupeCount > 0 && (
                <>
                  {' · '}
                  <button
                    type="button"
                    onClick={() => setExpandedDupes(s => ({ ...s, [key]: !s[key] }))}
                    style={{
                      border: 'none', background: 'transparent', cursor: 'pointer',
                      color: 'var(--text-muted)', padding: 0, font: 'inherit', textDecoration: 'underline',
                    }}
                  >
                    {showDupes ? `hide ${dupeCount} duplicate${dupeCount === 1 ? '' : 's'}` : `show ${dupeCount} duplicate${dupeCount === 1 ? '' : 's'}`}
                  </button>
                </>
              )}
            </span>
          </div>

          {p.sheet_refund_warnings && p.sheet_refund_warnings.length > 0 && (
            <div
              style={{
                background: '#fffbeb',
                border: '1px solid #fbbf24',
                borderRadius: 8,
                padding: '12px 16px',
                marginBottom: 12,
                fontSize: 13,
              }}
            >
              <strong>⚠ Possible refund for already-imported rows.</strong>
              <p style={{ color: 'var(--text-muted)', marginTop: 4, marginBottom: 8 }}>
                Review and remove from the sheet manually if these are real refunds:
              </p>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                {p.sheet_refund_warnings.map((w, wi) => (
                  <li key={wi}>
                    Credit {w.credit_date} {w.credit_amount} ({w.credit_name}) → sheet row {w.sheet_date} {w.sheet_amount}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {p.error && <div className="error-msg">{p.error}</div>}

          {p.rows.length > 0 && (
            <div className="preview-table">
              <table>
                <colgroup>
                  <col style={{ width: 36 }} />
                  <col style={{ width: 60 }} />
                  <col style={{ width: 80 }} />
                  <col style={{ width: '30%' }} />
                  <col style={{ width: '25%' }} />
                  <col />
                </colgroup>
                <thead>
                  <tr>
                    <th></th>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>Expense</th>
                    <th>Category</th>
                    <th>Raw</th>
                  </tr>
                </thead>
                <tbody>
                  {p.rows.map((r, ri) => [r, ri] as const).reverse().map(([r, ri]) => {
                    if (r.status === 'duplicate' && !showDupes) return null
                    return (
                    <tr
                      key={ri}
                      style={{
                        opacity: r.status === 'duplicate' ? 0.5 : 1,
                        background: r.status === 'needs_manual' ? '#fffbeb' : undefined,
                      }}
                    >
                      <td>
                        <button
                          type="button"
                          onClick={() => toggleSkip(mi, ri)}
                          title={r.status === 'duplicate' ? 'Import anyway' : 'Skip'}
                          style={{ border: 'none', background: 'transparent', cursor: 'pointer' }}
                        >
                          {r.status === 'duplicate' ? '⊘' :
                           r.status === 'needs_manual' ? '⚠' : '✓'}
                        </button>
                      </td>
                      <td>{r.date_short}</td>
                      <td className="amount">{r.amount_fmt}</td>
                      <td>
                        <input
                          type="text"
                          value={r.expense_name}
                          disabled={r.status === 'duplicate'}
                          onChange={(e) => updateRow(mi, ri, { expense_name: e.target.value })}
                          style={{ width: '100%', padding: '4px 6px', border: '1px solid var(--border)', borderRadius: 4 }}
                        />
                      </td>
                      <td>
                        <select
                          value={r.category}
                          disabled={r.status === 'duplicate'}
                          onChange={(e) => {
                            const cat = e.target.value
                            updateRow(mi, ri, {
                              category: cat,
                              status: cat === 'NEED MANUAL ENTRY' ? 'needs_manual' :
                                      r.status === 'duplicate' ? r.status : 'new',
                            })
                          }}
                          style={{ width: '100%', padding: '4px 6px', border: '1px solid var(--border)', borderRadius: 4 }}
                        >
                          {!p.categories.includes(r.category) && (
                            <option value={r.category}>{r.category}</option>
                          )}
                          {p.categories.map(c => (
                            <option key={c} value={c}>{c}</option>
                          ))}
                        </select>
                      </td>
                      <td className="name" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                        {r.raw_name}
                      </td>
                    </tr>
                  )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!showDupes && visibleRows.length === 0 && p.rows.length > 0 && (
            <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: 13 }}>
              All rows in this month are duplicates of the sheet — nothing to import.
            </div>
          )}
        </section>
        )
      })}

      {previews && (
        <div className="upload-card" style={{ marginTop: 16 }}>
          <button
            className="submit-btn"
            disabled={committing || totalToCommit === 0}
            onClick={commit}
          >
            {committing ? 'Writing to sheet...' : `Commit ${totalToCommit} rows to sheet`}
          </button>
        </div>
      )}
    </div>
  )
}
