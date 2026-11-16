import { useState } from 'react'

export interface AskState {
  question: string
  answerHow: string
  replyCode: string
  kind: string
  notBefore: string // yyyy-mm-dd from the date input, or ''
}

export const EMPTY_ASK: AskState = { question: '', answerHow: '', replyCode: '', kind: 'decide', notBefore: '' }

export const useAsk = () => useState<AskState>(EMPTY_ASK)

const KINDS: [string, string][] = [['decide', 'Decide'], ['confirm', 'Confirm'], ['release', 'Release'], ['review', 'Review']]

const NOTE = '· required when waiting on you'

// A date input's yyyy-mm-dd -> epoch seconds at local midnight.
export function localMidnight(day: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day)
  if (!m) return null
  return Math.floor(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime() / 1000)
}

export const askComplete = (a: AskState) => !!a.question.trim() && !!a.answerHow.trim()

// The ask fields of a write body; `task` adds ask_kind and not_before.
export function askBody(a: AskState, task: boolean): Record<string, unknown> {
  const out: Record<string, unknown> = { question: a.question.trim(), answer_how: a.answerHow.trim() }
  if (a.replyCode.trim()) out.reply_code = a.replyCode.trim()
  if (task) {
    out.ask_kind = a.kind
    const nb = localMidnight(a.notBefore)
    if (nb !== null) out.not_before = nb
  }
  return out
}

// Shown while the form waits on a human (mockup #s4): the question and how to answer are required.
export default function AskFields({ ask, setAsk, task, invalid }:
  { ask: AskState; setAsk: (a: AskState) => void; task: boolean; invalid: boolean }) {
  const set = (k: keyof AskState) => (e: { target: { value: string } }) => setAsk({ ...ask, [k]: e.target.value })
  const bad = (v: string) => invalid && !v.trim()
  return (
    <>
      <label className="field">
        <span>Question for you <i className="req" aria-hidden="true">*</i><em className="ask-note">{` ${NOTE}`}</em></span>
        <input value={ask.question} maxLength={300} onChange={set('question')} className={bad(ask.question) ? 'err' : undefined}
          aria-invalid={bad(ask.question) || undefined} />
      </label>
      <label className="field">
        <span>How to answer <i className="req" aria-hidden="true">*</i><em className="ask-note">{` ${NOTE}`}</em></span>
        <input value={ask.answerHow} maxLength={200} onChange={set('answerHow')} className={bad(ask.answerHow) ? 'err' : undefined}
          aria-invalid={bad(ask.answerHow) || undefined} />
      </label>
      <label className="field">
        <span>Reply code (optional)</span>
        <input value={ask.replyCode} maxLength={80} onChange={set('replyCode')} />
      </label>
      {task && (
        <div className="two">
          <label className="field">
            <span>Kind</span>
            <select value={ask.kind} onChange={set('kind')}>
              {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Not before (optional)</span>
            <input type="date" value={ask.notBefore} onChange={set('notBefore')} />
          </label>
        </div>
      )}
    </>
  )
}
