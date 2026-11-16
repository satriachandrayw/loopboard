import { useEffect, useState } from 'react'

// The reply code in a monospace chip and a Copy button that copies exactly that code.
export default function CopyCode({ code }: { code: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  useEffect(() => {
    if (state === 'idle') return
    const t = setTimeout(() => setState('idle'), 2000)
    return () => clearTimeout(t)
  }, [state])
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setState('copied')
    } catch {
      setState('failed') // no clipboard (plain http) or permission refused
    }
  }
  return (
    <>
      <code className="code">{code}</code>
      <button type="button" className="copy" onClick={() => void copy()} aria-label={`Copy ${code}`}>
        {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy'}
      </button>
    </>
  )
}
