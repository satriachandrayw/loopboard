-- Needs you questions (docs/design-needs-you-questions.md). Expand-only: new nullable columns, no backfill.

alter table tasks add column question text;
alter table tasks add column answer_how text;
alter table tasks add column reply_code text;
alter table tasks add column ask_kind text;
alter table tasks add column not_before integer;

alter table epics add column question text;
alter table epics add column answer_how text;
alter table epics add column reply_code text;
