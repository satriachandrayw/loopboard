-- Tasks between epics and items (docs/design-tasks.md). Expand-only, except `relations`, which is
-- rebuilt so its type checks also accept 'task'.

create table tasks (
  id integer primary key autoincrement,
  project_id integer not null references projects(id),
  epic_id integer references epics(id),
  seq integer not null,
  key text unique not null,
  type text not null default 'task' check (type in ('task','bug')),
  summary text not null,
  description text not null,
  done_when text not null,
  status text not null default 'todo' check (status in ('todo','in_progress','review','done','canceled')),
  priority text not null default 'medium' check (priority in ('high','medium','low')),
  owner text not null,
  waiting_on text,
  reporter text not null,
  refs text not null default '[]',
  merged_into integer references tasks(id),
  origin_item_id integer references items(id),
  done_confirmed_at integer,
  last_activity_at integer not null,
  stalled_since integer,
  created_at integer not null,
  updated_at integer not null,
  unique (project_id, seq)
);

alter table items add column task_id integer references tasks(id);

create index items_task_id on items(task_id);
create index tasks_epic_id on tasks(epic_id);
create index tasks_project_id on tasks(project_id);

-- Backfill: one task per item filed to an epic or standalone, keys per project in item id order.
-- An item canceled at its source gives a canceled task, so no epic's column or progress moves.
-- An item with no waiting_on (done or canceled at its source) waits on that source.
insert into tasks(project_id, epic_id, seq, key, type, summary, description, done_when, status, priority,
                  owner, waiting_on, reporter, refs, origin_item_id, last_activity_at, created_at, updated_at)
select f.project_id, f.epic_id,
       row_number() over (partition by f.project_id order by f.id),
       p.key || '-' || row_number() over (partition by f.project_id order by f.id),
       'task', f.title,
       'Migrated from ' || coalesce(f.url, f.source || ':' || f.external_id),
       'The linked work is live.', case when f.status_category = 'canceled' then 'canceled' else 'todo' end,
       'medium',
       coalesce(nullif(trim(f.owner), ''), f.source), coalesce(f.waiting_on, 'source:' || f.source), 'migration', '[]', f.id,
       f.last_activity_at, f.created_at, f.updated_at
from (
  select i.id, i.epic_id, i.title, i.url, i.source, i.external_id, i.owner, i.waiting_on, i.status_category,
         i.last_activity_at, i.created_at, i.updated_at,
         case when i.filing = 'epic' then e.project_id else i.project_id end as project_id
  from items i left join epics e on e.id = i.epic_id
  where i.filing in ('epic', 'standalone')
) as f
-- left join: a filed item without a project fails the NOT NULL on tasks.project_id and aborts the
-- migration, instead of silently getting no task.
left join projects p on p.id = f.project_id
order by f.id;

update items set task_id = (select id from tasks where origin_item_id = items.id)
where filing in ('epic', 'standalone');

insert into events(at, actor, via, subject_type, subject_id, kind, payload)
select cast(strftime('%s', 'now') as integer), 'migration', 'migration', 'task', id, 'task.created',
       json_object('key', key, 'origin_item_id', origin_item_id)
from tasks where reporter = 'migration' order by id;

create table relations_new (
  id integer primary key autoincrement,
  kind text not null check (kind in ('blocks')),
  from_type text check (from_type in ('epic','item','task')),
  from_id integer,
  to_type text check (to_type in ('epic','item','task')),
  to_id integer,
  created_at integer not null,
  unique (kind, from_type, from_id, to_type, to_id)
);
insert into relations_new(id, kind, from_type, from_id, to_type, to_id, created_at)
select id, kind, from_type, from_id, to_type, to_id, created_at from relations;
drop table relations;
alter table relations_new rename to relations;
