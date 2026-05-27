-- app/services/schema.sql
create table if not exists trips (
  slug text primary key,
  data jsonb not null,
  manual_routes jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists checklist_state (
  trip_slug text not null,
  item_key  text not null,
  app_user  text not null default '',
  checked   boolean not null,
  updated_at timestamptz not null default now(),
  primary key (trip_slug, item_key, app_user)
);
