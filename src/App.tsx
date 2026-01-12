import { useState, useRef, type DragEvent, type ChangeEvent } from 'react'

interface Transaction {
  date: string
  name: string
  amount: number
}

function parseCSV(text: string): Transaction[] {
  const lines = text.trim().split('\n')
  if (lines.length < 2) return []

  const headers = lines[0].split(',').map(h => h.trim().replace(/"/g, ''))
  const dateIdx = headers.findIndex(h => h.toLowerCase() === 'date')
  const nameIdx = headers.findIndex(h => h.toLowerCase() === 'name')
  const amountIdx = headers.findIndex(h => h.toLowerCase() === 'amount')

  if (dateIdx === -1 || nameIdx === -1 || amountIdx === -1) {
    throw new Error('CSV must have Date, Name, and Amount columns')
  }

  const transactions: Transaction[] = []
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(',').map(c => c.trim().replace(/"/g, ''))
    const amount = parseFloat(cols[amountIdx])
    if (amount < 0) {
      transactions.push({
        date: cols[dateIdx],
        name: cols[nameIdx],
        amount,
      })
    }
  }
  return transactions
}

function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`
}

function formatAmount(amount: number): string {
  return `$${Math.abs(amount).toFixed(2)}`
}

interface ImportResult {
  total_added: number
  results: { year: number; month: number; added: number }[]
}

const API_URL = 'http://localhost:8000'

export default function App() {
  const [file, setFile] = useState<File | null>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [dragActive, setDragActive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = async (f: File) => {
    if (!f.name.endsWith('.csv')) {
      setError('Please upload a CSV file')
      return
    }
    setError(null)
    setFile(f)
    try {
      const text = await f.text()
      setTransactions(parseCSV(text))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to parse CSV')
      setTransactions([])
    }
  }

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
    setTransactions([])
    setError(null)
    setResult(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const handleSubmit = async () => {
    if (!file || !transactions.length) return
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      console.log("formData: ", formData)
      const res = await fetch(`${API_URL}/import`, {
        method: 'POST',
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Import failed')
      }

      const data: ImportResult = await res.json()
      setResult(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Finance Tracker</h1>
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
          <div className="dropzone-hint">Supports Chase, Amex, and other exports</div>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept=".csv"
          onChange={onChange}
          hidden
        />

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

        <button
          className="submit-btn"
          disabled={!transactions.length || loading}
          onClick={handleSubmit}
        >
          {loading ? 'Processing...' : `Import ${transactions.length || ''} Transactions`}
        </button>

        {result && (
          <div className="success-msg">
            <strong>Import Complete</strong>
            <p>{result.total_added} transactions added</p>
          </div>
        )}
      </div>

      {transactions.length > 0 && (
        <section className="preview">
          <div className="preview-header">
            <span className="preview-title">Preview</span>
            <span className="preview-count">{transactions.length} transactions</span>
          </div>
          <div className="preview-table">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Description</th>
                  <th>Amount</th>
                </tr>
              </thead>
              <tbody>
                {transactions.slice(0, 8).map((t, i) => (
                  <tr key={i}>
                    <td>{t.date}</td>
                    <td className="name">{t.name}</td>
                    <td className="amount">{formatAmount(t.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {transactions.length > 8 && (
              <div className="preview-more">+{transactions.length - 8} more</div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
