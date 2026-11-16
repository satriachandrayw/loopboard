# Needs you: every row carries its question

Status: approved by the owner, 16 Nov 2026. Public copy of the private design note.

## Problem

The Needs you list shows only a reason ("waiting on you", "review · you", "merged, not live"). Opening a row shows the task, but nowhere does it say what the human is being asked or how to answer. On a real board about half of the rows were not the human's at all: PR reviews the agent hadn't done yet, ideas with no start date, epic rows repeating their own tasks, and one row per merged-not-live PR for what is really one release decision.

## Goals

- Every Needs you row says what kind of answer it needs, the question in one line, two lines of context, and exactly how to answer.
- Opening a row puts the answer box on top and everything needed to decide below it: context, done-when, links with their live state, the epic's next step, recent activity.
- Nothing can be set to wait on a human without a question and how to answer.
- Merged-not-live work folds into one Release row per project.
- Asks that aren't due yet sit under Later until their date.

## Non-goals

- **No reply box in Loopboard.** The human answers where the work lives: a reply to their agent in chat, or a button Loopboard already has (Confirm done). Loopboard stays project management, not a control plane.
- No change to stall rules, columns, derivation of task status, or the connectors.

## Decisions

1. **Answer kinds:** Decide, Review, Release, Confirm, Later. The list groups rows by kind in that order (Later collapsed), oldest first inside each group.
2. **Where the human answers:** outside Loopboard (chat reply code shown with a Copy button), except Confirm done, which stays a Loopboard button.
3. **Synced rows get a standard question** computed at read time, so PR and card rows never show without one:
   - an agent says done, no link proves it → Confirm: "The agent says this is done. Is it?" (Confirm done button);
   - merged into a non-live branch → folded into the project's Release row: "Release <project> to its live branch?", reply `release <project>`;
   - a linked card blocked for input → Decide: "What should card <id> do next?", reply `<id>: <answer>`;
   - a linked open PR waiting on the human → Review: "Merge PR <repo>#<n>?", reply `merge <repo>#<n>`;
   - a linked card in review waiting on the human → Review: "Approve card <id>?", reply `push <id>`;
   - anything else waiting on the human with no stored question → Decide, flagged "no question recorded", reply `<KEY>?`.
   A question stored on the task always wins over the computed one.
4. **Stored fields** on tasks: `question`, `answer_how`, optional `reply_code` (the exact text the Copy button copies), `ask_kind`, optional `not_before`. Epics get `question`, `answer_how`, `reply_code`.
5. **Rule:** creating a task or epic that waits on a human, or changing `waiting_on` to a human, needs `question` and `answer_how` (422 otherwise). Items synced by connectors are exempt; rule 3 covers them.
6. **Every reason moves to the task that causes it.** Epic rows appear only when the epic itself waits on the human; task-derived reasons (awaiting confirmation, review, merged not live, blocked) show once, on the task.
7. **Desktop** (≥ 1100 px): the list on the left, the selected row's answer box and details on the right. Phone: tap a row to open its task page.

## Rejected

- A reply box on the detail screen (option b): turns Loopboard into a control surface and duplicates the chat path.
- Leaving synced rows without a question until someone adds one: the list would keep showing rows nobody can act on.
