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

create table if not exists feedback (
  id          text primary key,
  author      text not null,
  kind        text not null,                 -- 'idea' | 'bug'
  body        text not null,
  status      text not null default 'open',  -- 'open' | 'planned' | 'done'
  image       bytea,
  image_mime  text,
  created_at  double precision not null default extract(epoch from now())
);

create table if not exists trip_comments (
  id          text primary key,
  trip_slug   text not null,
  author      text not null,
  body        text not null,
  created_at  double precision not null default extract(epoch from now())
);
create index if not exists trip_comments_slug_idx on trip_comments (trip_slug, created_at);

-- Lock down Supabase's auto-generated data API: with RLS enabled and no
-- policies, the anon/authenticated API roles get zero access. The app connects
-- as the postgres role (via DATABASE_URL), which bypasses RLS, so it is
-- unaffected. Idempotent — safe to re-run.
alter table public.trips enable row level security;
alter table public.checklist_state enable row level security;
alter table public.feedback enable row level security;
alter table public.trip_comments enable row level security;
