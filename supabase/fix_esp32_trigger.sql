-- ============================================================
-- sensor_data INSERT: "latest_sensor_data does not exist"
-- Supabase -> SQL Editor -> TAMAMINI sec -> Run
-- ============================================================

-- 1) sensor_data uzerindeki TUM trigger'lari kaldir
DO $$
DECLARE
  trg RECORD;
BEGIN
  FOR trg IN
    SELECT t.tgname AS name
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'sensor_data'
      AND NOT t.tgisinternal
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.sensor_data CASCADE', trg.name);
    RAISE NOTICE 'Trigger silindi: %', trg.name;
  END LOOP;
END $$;

-- 2) latest_sensor_data gecen TUM public fonksiyonlari kaldir
DO $$
DECLARE
  fn RECORD;
BEGIN
  FOR fn IN
    SELECT p.oid,
           n.nspname,
           p.proname,
           pg_get_function_identity_arguments(p.oid) AS args
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.prosrc ILIKE '%latest_sensor_data%'
  LOOP
    EXECUTE format(
      'DROP FUNCTION IF EXISTS %I.%I(%s) CASCADE',
      fn.nspname,
      fn.proname,
      fn.args
    );
    RAISE NOTICE 'Fonksiyon silindi: %.%(%)', fn.nspname, fn.proname, fn.args;
  END LOOP;
END $$;

-- 3) Eski isimler (elle eklenmis olabilir)
DROP TRIGGER IF EXISTS on_sensor_data_insert ON public.sensor_data CASCADE;
DROP TRIGGER IF EXISTS sync_sensor_data ON public.sensor_data CASCADE;
DROP TRIGGER IF EXISTS sensor_data_to_latest ON public.sensor_data CASCADE;
DROP TRIGGER IF EXISTS trg_sync_latest_sensor ON public.sensor_data CASCADE;
DROP TRIGGER IF EXISTS trigger_sensor_data_insert ON public.sensor_data CASCADE;

DROP FUNCTION IF EXISTS public.sync_to_latest_sensor_data() CASCADE;
DROP FUNCTION IF EXISTS public.handle_sensor_data_insert() CASCADE;
DROP FUNCTION IF EXISTS public.sync_latest_sensor_status() CASCADE;

-- 4) Kontrol: trigger kaldi mi?
SELECT t.tgname AS kalan_trigger
FROM pg_trigger t
JOIN pg_class c ON c.oid = t.tgrelid
WHERE c.relname = 'sensor_data'
  AND NOT t.tgisinternal;

-- 5) Kontrol: latest_sensor_data gecen fonksiyon kaldi mi?
SELECT p.proname AS kalan_fonksiyon
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
  AND p.prosrc ILIKE '%latest_sensor_data%';
