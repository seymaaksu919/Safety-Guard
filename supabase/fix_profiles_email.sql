-- Sadece email sutunu ve RPC eksikse — SQL Editor'da calistirin (30 sn)

alter table public.profiles add column if not exists email text;

-- Asagidaki fonksiyon + grant icin tam dosya:
-- supabase/profiles_dashboard.sql (son 25 satir: get_dashboard_users)
