-- Dashboard: kullanici adlari (opsiyonel — SQL Editor'da bir kez calistirin)

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  full_name text,
  email text,
  updated_at timestamptz default now()
);

-- Eski tabloda email yoksa ekle (dashboard API 400 hatasini onler)
alter table public.profiles add column if not exists email text;
alter table public.profiles add column if not exists updated_at timestamptz default now();

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_authenticated" on public.profiles;
create policy "profiles_select_authenticated"
  on public.profiles for select
  to authenticated
  using (true);

-- Web dashboard (dashboard_api.py anon key) isimleri okuyabilsin
drop policy if exists "profiles_select_anon" on public.profiles;
create policy "profiles_select_anon"
  on public.profiles for select
  to anon
  using (true);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own"
  on public.profiles for insert
  to authenticated
  with check (auth.uid() = id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own"
  on public.profiles for update
  to authenticated
  using (auth.uid() = id);

-- Yeni kayit -> profiles satiri
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, full_name, email)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'full_name', ''),
    coalesce(new.email, '')
  )
  on conflict (id) do update
  set
    full_name = excluded.full_name,
    email = excluded.email,
    updated_at = now();
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Mevcut auth kullanicilarini profiles'a kopyala (bir kez)
insert into public.profiles (id, full_name, email)
select
  id,
  coalesce(raw_user_meta_data->>'full_name', ''),
  coalesce(email, '')
from auth.users
on conflict (id) do update
set full_name = excluded.full_name, email = excluded.email;

-- Web dashboard: anon key ile tum kayitli hesaplari oku (isim listesi)
create or replace function public.get_dashboard_users()
returns table (
  id uuid,
  full_name text,
  email text
)
language sql
security definer
set search_path = public
as $$
  select
    u.id,
    coalesce(nullif(trim(p.full_name), ''), nullif(trim(u.raw_user_meta_data->>'full_name'), ''), '')::text,
    coalesce(nullif(trim(p.email), ''), nullif(trim(u.email::text), ''), '')::text
  from auth.users u
  left join public.profiles p on p.id = u.id
  order by 2, 3;
$$;

revoke all on function public.get_dashboard_users() from public;
grant execute on function public.get_dashboard_users() to anon, authenticated, service_role;
