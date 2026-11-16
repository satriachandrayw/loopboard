import { useEffect, useState } from 'react'

// The reply code in a monospace chip and a Copy button that copies exactly that code.
export default function CopyCode({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(t)
  }, [copied])
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <>
      <code className="code">{code}</code>
      <button type="button" className="copy" onClick={() => void copy()} aria-label={`Copy ${code}`}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </>
  )
}
