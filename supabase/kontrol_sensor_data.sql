-- Supabase SQL Editor (proje: tsslkuwpqqvxxhuwttbk) → Run
-- Son 15 kayit (ESP32 verisi burada gorunur)
SELECT id, user_id, device_id, heart_rate, body_temp, ambient_temp,
       gas_level, gas_percent, status, risk, created_at
FROM public.sensor_data
ORDER BY created_at DESC
LIMIT 15;

-- Toplam satir sayisi
SELECT count(*) AS toplam FROM public.sensor_data;

-- Belirli kullanici (api_mobil.py DEFAULT_USER_ID ile ayni olmali)
-- SELECT * FROM public.sensor_data
-- WHERE user_id = '5757a1d7-b497-4b66-b5d1-2a72e3261a73'
-- ORDER BY created_at DESC LIMIT 10;
