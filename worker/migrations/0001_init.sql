create table projects (
  id integer primary key autoincrement,
  key text unique not null,
  name text not null,
  created_at integer not null
);

create table epics (
  id integer primary key autoincrement,
  project_id integer not null references projects(id),
  seq integer not null,
  key text unique not null,
  title text not null,
  goal text,
  manual_column text not null check (manual_column in ('backlog','todo','canceled')),
  board_column text not null,
  stage text not null check (stage in ('idea','spec','plan','build','review','ship')),
  owner text,
  next_step text,
  waiting_on text,
  home_url text,
  spec_url text,
  plan_url text,
  done_confirmed_at integer,
  done_at integer,
  last_activity_at integer not null,
  stalled_since integer,
  created_at integer not null,
  updated_at integer not null,
  unique (project_id, seq)
);

create table items (
  id integer primary key autoincrement,
  source text not null,
  external_id text not null,
  project_id integer references projects(id),
  epic_id integer references epics(id),
  filing text not null check (filing in ('unfiled','epic','standalone','ignored')),
  title text not null,
  url text,
  status_category text not null check (status_category in ('backlog','todo','in_progress','blocked','review','done','canceled')),
  raw_status text,
  owner text,
  waiting_on text,
  blocked_reason text,
  next_step text,
  last_activity_at integer not null,
  merged_at integer,
  live_at integer,
  stalled_since integer,
  created_at integer not null,
  updated_at integer not null,
  unique (source, external_id)
);

create table relations (
  id integer primary key autoincrement,
  kind text not null check (kind in ('blocks')),
  from_type text check (from_type in ('epic','item')),
  from_id integer,
  to_type text check (to_type in ('epic','item')),
  to_id integer,
  created_at integer not null,
  unique (kind, from_type, from_id, to_type, to_id)
);

create table events (
  id integer primary key autoincrement,
  at integer not null,
  actor text not null,
  via text not null,
  subject_type text not null,
  subject_id integer not null,
  kind text not null,
  payload text not null
);

create trigger events_no_update before update on events
begin
  select raise(abort, 'events are append-only');
end;

create trigger events_no_delete before delete on events
begin
  select raise(abort, 'events are append-only');
end;

create table api_tokens (
  id integer primary key autoincrement,
  name text unique not null,
  token_hash text unique not null,
  scopes text not null,
  source text,
  created_at integer not null,
  revoked_at integer
);

create table sources (
  name text primary key,
  stall_hours real not null default 24,
  updated_at integer not null
);
