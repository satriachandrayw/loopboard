# Epic Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every epic's description (the existing `goal` field) on its board card, call it "Description" in the UI, and require it whenever an epic is created.

**Architecture:** No schema change. The API keeps the field name `goal`; the board card payload gains `goal`; `EpicIn.goal` becomes required and non-blank; `EpicPatch` can change it but never blank or null it. The web card renders it as two clamped lines; the form and epic detail relabel it "Description".

**Tech Stack:** Python 3.13 FastAPI on Cloudflare Workers + D1 (pydantic models), pytest; React + TypeScript, Vitest + Testing Library.

**Spec:** this plan is step 1 of the Jira-style tasks design (epic descriptions). The requirements it implements are copied into Global Constraints below; the rest of that design (tasks, Tasks board) is out of scope here.

## Global Constraints

- No migration. The column stays `epics.goal`; the JSON field stays `goal` in every request and response (backward compatible for API clients that already send it).
- `POST /api/projects/{key}/epics`: `goal` is required, max 2000 characters, and must contain a non-whitespace character; missing, `null`, `""` or whitespace-only → 422. The stored value is the stripped string.
- `PATCH /api/epics/{key}`: `goal` stays optional; when given it follows the same rule (non-blank string, stripped, max 2000). `null` → 422 (`goal cannot be null`). Omitting it leaves it unchanged.
- Existing epics whose `goal` is null keep working everywhere: the card shows no description and never the text "null".
- Board card JSON (`GET /api/board`, `GET /api/needs-you` epic rows if they use the card, the card returned by epic writes, and `epic` in `GET /api/epics/{key}`) carries `goal: string | null`. The write responses must still equal the GET card (existing test `test_epic_write_responses_match_get_card`).
- UI copy: the label is **Description** (form field, epic detail heading). Card: description under the title, clamped to 2 lines with an ellipsis, on desktop and at 390 px.
- Form: an empty or whitespace-only description shows the error "Add a description: what this epic is for." and posts nothing.
- Repo rules from `docs/plans/2026-11-12-loopboard-v1a.md` Global Constraints still hold: neutral names (`owner`, `DEMO`), no deploy/push, `bash scripts/test.sh` is the gate, and `bash scripts/acceptance-local.sh` must print `ACCEPTANCE PASS`.

## Review Focus

- Whitespace-only description ("   ") → 422 from the API and the form error in the UI (Task 1 test `test_create_epic_blank_goal_is_422`, Task 2 test `test_blank_description_is_refused`).
- An existing epic with `goal = null` renders its card with no `.desc` element (Task 2 `test_card_without_goal_has_no_description`).
- A 2000-character description doesn't stretch the card: `.desc` has the 2-line clamp (Task 2 `test_card_shows_description_clamped`).
- Unfiled → "+ New epic…" requires a description too, and nothing gets filed if the epic isn't created (Task 2 `test_new_epic_from_row_prefills_creates_then_files` updated, plus `test_new_epic_from_row_without_description_files_nothing`).
- PATCH can't blank a description (Task 1 `test_patch_goal_cannot_be_blanked_or_nulled`).

---

### Task 1: Worker: required description, card carries it

**Files:**
- Modify: `worker/src/loopboard/model.py` (`EpicIn.goal`, `EpicPatch.goal`, shared validator)
- Modify: `worker/src/loopboard/writes.py:13` (`NOT_NULL` gains `"goal"`)
- Modify: `worker/src/loopboard/reads.py` (`_card` adds `"goal"`; the epic-detail `card.update(...)` no longer needs to add it)
- Modify: `worker/tests/test_writes.py` (`mk_epic` defaults `goal="Demo goal."`), `worker/tests/test_model.py`, `worker/tests/test_reads.py`
- Modify: any other worker test that posts an epic without `goal` (grep `/epics"` in `worker/tests`)
- Modify: `scripts/acceptance-local.sh:129` (the create-epic body gains `"goal":"Acceptance goal."`)
- Modify: `docs/api.md` (epic create body: `goal` required, non-blank; PATCH: `goal` can't be null or blank; card fields list `goal`)

**Interfaces:**
- Produces: card dicts from `reads._card` include key `"goal"` (`str | None`). `EpicIn(goal=...)` is required.

- [ ] **Step 1: Write the failing tests**

```python
# test_model.py
def test_epic_goal_required_and_stripped():
    assert EpicIn(title="T", waiting_on="agent:a", goal="  Ship it  ").goal == "Ship it"
    for bad in (None, "", "   "):
        with pytest.raises(ValueError):
            EpicIn(title="T", waiting_on="agent:a", goal=bad)
    with pytest.raises(ValueError):
        EpicIn(title="T", waiting_on="agent:a")

# test_writes.py
async def test_create_epic_blank_goal_is_422(make_app, client_for):
    app, repo, h = await setup(make_app)
    await mk_project(client_for, app, h)
    for g in ("", "   "):
        assert (await mk_epic(client_for, app, h, goal=g)).status_code == 422
    r = await req(client_for, app, h, "POST", "/api/projects/DEMO/epics", {"title": "E", "waiting_on": "agent:a"})
    assert r.status_code == 422

async def test_patch_goal_cannot_be_blanked_or_nulled(make_app, client_for):
    app, repo, h = await seeded(make_app, client_for)
    for g in (None, "", "  "):
        r = await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"goal": g})
        assert r.status_code == 422
    r = await req(client_for, app, h, "PATCH", "/api/epics/DEMO-E1", {"goal": " New "})
    assert r.status_code == 200 and r.json()["goal"] == "New"

# test_reads.py
async def test_board_card_carries_goal(...):
    # one epic created with goal "Demo goal.", one inserted by SQL with goal NULL
    # GET /api/board → the two cards have goal == "Demo goal." and goal is None
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd worker && uv run --python 3.13 pytest -q tests/test_model.py tests/test_writes.py tests/test_reads.py`
Expected: the new tests FAIL (goal optional today; card has no `goal`).

- [ ] **Step 3: Implement**

In `model.py`, add one `field_validator("goal")` used by both models: `None` passes through only for `EpicPatch` (where `writes.NOT_NULL` then rejects an explicit null); otherwise strip, and raise when empty. `EpicIn.goal: str = Field(max_length=2000)` (required). Add `"goal"` to `NOT_NULL`. Add `"goal": e["goal"]` to `_card`.

- [ ] **Step 4: Make the whole suite and the acceptance pass**

Run: `bash scripts/test.sh && bash scripts/acceptance-local.sh`
Expected: all suites pass; last line `ACCEPTANCE PASS`.

- [ ] **Step 5: Commit**

```bash
git add worker docs/api.md scripts/acceptance-local.sh
git commit -m "feat(worker): require an epic description and carry it on the board card"
```

### Task 2: Web: description on the card, "Description" in the form and detail

**Files:**
- Modify: `web/src/types.ts` (`Card.goal: string | null`)
- Modify: `web/src/components/Card.tsx` (render `<p className="desc">{card.goal}</p>` after the title when `card.goal` is non-empty)
- Modify: `web/src/index.css` (`.card .desc`: muted color, 11.5px, `display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; margin:0 0 4px`; keep `white-space: normal`)
- Modify: `web/src/components/NewEpicForm.tsx` (label `Description`; required check before posting; always send `goal`)
- Modify: `web/src/screens/EpicDetail.tsx:94` (heading `Description` instead of `Goal`; keep line breaks with `white-space: pre-line` on `.goal`)
- Test: `web/src/components/Card.test.tsx`, `web/src/components/NewEpicForm.test.tsx`, `web/src/screens/EpicDetail.test.tsx`, `web/src/screens/Unfiled.test.tsx`; add `goal: null` to the `base` card fixtures that type-check against `Card`

**Interfaces:**
- Consumes: `goal` on every card from Task 1.

- [ ] **Step 1: Write the failing tests**

```tsx
// Card.test.tsx
it('test_card_shows_description_clamped', () => {
  const { container } = show({ goal: 'Ship the thing. '.repeat(120) })
  const d = container.querySelector('.desc')!
  expect(d.textContent).toContain('Ship the thing.')
  expect(d.className).toBe('desc')
})
it('test_card_without_goal_has_no_description', () => {
  const { container } = show({ goal: null })
  expect(container.querySelector('.desc')).toBeNull()
  expect(container.textContent).not.toContain('null')
})

// NewEpicForm.test.tsx: the first test types into getByLabelText('Description') instead of 'Goal';
// rename test_agent_waiting_on_and_goal_omitted_when_blank → test_blank_description_is_refused:
//   title 'T', description '   ', click Create →
//   screen.getByRole('alert').textContent === 'Add a description: what this epic is for.' and posts(f) is []

// EpicDetail.test.tsx test_goal_links_and_relations: expects the heading text 'Description'
// (not 'Goal') above 'Ship the thing'.

// Unfiled.test.tsx test_new_epic_from_row_prefills_creates_then_files: type 'Why' into the
// dialog's 'Description' field before Create; posts[0].body.goal === 'Why'.
// New: test_new_epic_from_row_without_description_files_nothing: Create with an empty
// description → alert shown, posts(f) is [] (no epic, no filing).
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd web && npx vitest run`
Expected: the new and changed tests FAIL.

- [ ] **Step 3: Implement** the files above.

- [ ] **Step 4: Run every suite and check the screens**

Run: `bash scripts/test.sh`
Expected: all pass, web build succeeds.
Then the reviewer takes desktop and 390 px screenshots of the board with seeded demo data (every seeded epic has a description) and compares the card with the approved mockup "Epic card gets its description".

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat(web): show the epic description on board cards; require it in the new-epic form"
```

## Out of scope (owner-side, done by the operator after merge, not by this card)

- The private write tool and the daily/weekly proposal jobs always send a description when they create an epic.
- The 12 live epics without a description are backfilled through the normal write path after the owner's OK.
- Deploy (owner's OK).
