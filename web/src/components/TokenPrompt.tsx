import { useState } from 'react'
import { setToken } from '../token'

export default function TokenPrompt({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState('')
  return (
    <form
      className="token-prompt"
      onSubmit={(e) => {
        e.preventDefault()
        if (!value.trim()) return
        setToken(value.trim())
        onSaved()
      }}
    >
      <p>Enter your Loopboard token to continue.</p>
      <label>
        Token
        <input type="password" value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      <button type="submit">Save</button>
    </form>
  )
}
