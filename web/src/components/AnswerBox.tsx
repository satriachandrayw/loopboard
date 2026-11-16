import type { ReactNode } from 'react'
import CopyCode from './CopyCode'
import type { Ask } from '../types'

export const KIND_LABEL: Record<string, string> = {
  decide: 'Decide', review: 'Review', release: 'Release', confirm: 'Confirm', later: 'Later',
}

export function KindLabel({ kind }: { kind: string }) {
  return <span className={`kind k-${kind}`}>{KIND_LABEL[kind] ?? kind}</span>
}

// The question with a leading `?`, then how to answer and the reply code with Copy.
export function Question({ ask, children }: { ask: Ask; children?: ReactNode }) {
  return (
    <>
      {ask.missing_question && <span className="flag nq">No question recorded</span>}
      {ask.question && <p className="q">{ask.question}</p>}
      {children}
      {(ask.answer_how || ask.reply_code) && (
        <div className="how">
          {ask.answer_how && <span>{ask.answer_how}</span>}
          {ask.reply_code && <CopyCode code={ask.reply_code} />}
        </div>
      )}
    </>
  )
}

// Task page and desktop detail: the answer box on top. `action` holds an existing button (Confirm done).
export default function AnswerBox({ ask, action }: { ask: Ask; action?: ReactNode }) {
  return (
    <section className="box ans" aria-label="Your answer">
      <h2 className="bh">Your answer</h2>
      <Question ask={ask} />
      {action && <div className="btns">{action}</div>}
    </section>
  )
}
