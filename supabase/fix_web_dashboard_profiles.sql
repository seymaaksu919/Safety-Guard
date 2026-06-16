-- MEVCUT profiles tablonuz icin (id, username, full_name, created_at)
-- Supabase -> SQL Editor -> Run (30 saniye)

-- 1) Web dashboard anon key ile profiles okuyabilsin
alter table public.profiles enable row level security;

drop policy if exists "profiles_select_anon" on public.profiles;
create policy "profiles_select_anon"
  on public.profiles for select
  to anon
  using (true);

-- 2) RPC: tum kayitli kullanicilar (RLS'i asar — isim listesi icin)
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
    coalesce(
      nullif(trim(p.full_name), ''),
      nullif(trim(u.raw_user_meta_data->>'full_name'), ''),
      ''
    )::text,
    coalesce(
      nullif(trim(p.username), ''),
      nullif(trim(u.email::text), ''),
      ''
    )::text
  from auth.users u
  left join public.profiles p on p.id = u.id
  order by 2, 3;
$$;

revoke all on function public.get_dashboard_users() from public;
grant execute on function public.get_dashboard_users() to anon, authenticated, service_role;
