# Supabase Kurulum & Yapılandırma Rehberi

## 📋 Proje Durumu

Uygulamanız Supabase ile **Authentication (Giriş/Kayıt)** için ayarlanmıştır. Aşağıdaki güncellemeler yapıldı:

✅ **Temizlemeler:**
- Olmayan `sensor_data` tablosuna referanslar kaldırıldı
- Yanlış sensor modelleri temizlendi
- Gereksiz stream bağlantıları kaldırıldı

✅ **Yeni Yapı:**
- `AuthService` oluşturuldu - merkezi authentication yönetimi
- Supabase imports optimize edildi
- Hata mesajları Türkçeleştirildi

---

## 🔐 Supabase Kurulum Adımları

### 1️⃣ Supabase Hesabı Oluşturma
1. https://supabase.com adresine git
2. "Sign Up" butonuna tıkla
3. E-posta veya GitHub ile kayıt ol
4. Yeni bir proje oluştur

### 2️⃣ API Credentials Al
1. Supabase Dashboard'a git
2. **Settings** → **API** kısmına git
3. Aşağıdaki değerleri kopyala:
   - `Project URL` (API base URL)
   - `anon public` key (bu dosyada zaten kullanılıyor)

### 3️⃣ Credentials Güvenli Şekilde Kullan
**ÖNEMLİ:** Hardcoded credentials kullanmak güvenlik riski oluşturur!

`lib/main.dart` dosyasında şu şekilde yapılabilir:

```dart
// OPSIYONEL: Environment değişkenleri kullan
const String SUPABASE_URL = String.fromEnvironment('SUPABASE_URL',
    defaultValue: 'https://tsslkuwpqqvxxhuwttbk.supabase.co');
const String SUPABASE_ANON_KEY = String.fromEnvironment('SUPABASE_ANON_KEY',
    defaultValue: 'sb_publishable_9cX7xtFcc85spzMuD2XBgQ_ro1YcEJU');

await Supabase.initialize(
  url: SUPABASE_URL,
  anonKey: SUPABASE_ANON_KEY,
);
```

---

## 🗄️ Database Tablolar Oluşturma

Supabase Dashboard'da **SQL Editor** kullanarak aşağıdaki tabloları oluştur:

### A. Users Tablosu (AUTH otomatik oluşturur)
Supabase Auth zaten user bilgilerini yönetir. Ek user data için:

```sql
CREATE TABLE public.user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  full_name TEXT,
  email TEXT UNIQUE,
  avatar_url TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Row Level Security (RLS) Politikaları:
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own profile"
  ON public.user_profiles FOR SELECT
  USING (auth.uid() = id);

CREATE POLICY "Users can update their own profile"
  ON public.user_profiles FOR UPDATE
  USING (auth.uid() = id);
```

### B. Sensor Data Tablosu (Eğer sensör verisi saklayacaksan):

```sql
CREATE TABLE public.sensor_readings (
  id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  temperature FLOAT8,
  humidity FLOAT8,
  heart_rate INT,
  gas_level INT,
  created_at TIMESTAMP DEFAULT NOW()
);

-- RLS Politikaları:
ALTER TABLE public.sensor_readings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view their own readings"
  ON public.sensor_readings FOR SELECT
  USING (auth.uid() = user_id);

CREATE POLICY "Users can insert their own readings"
  ON public.sensor_readings FOR INSERT
  WITH CHECK (auth.uid() = user_id);
```

---

## 🎯 Kod Yapısı

```
lib/
├── main.dart                 # Supabase initialization
├── services/
│   └── auth_service.dart     # Authentication işlemleri
├── auth_screen.dart          # Giriş/Kayıt UI
├── dashboard_screen.dart     # Ana sayfa (korumalı)
└── splash_screen.dart        # Yükleme ekranı
```

---

## 🔄 Akış Nasıl Çalışır?

```
App Başlar
    ↓
SplashScreen (4 saniye)
    ↓
AuthService.currentSession kontrol et
    ↓
Oturum Var? → Dashboard'a Git : AuthScreen'e Git
    ↓
AuthScreen
  └─ Giriş Yap (signIn)
  └─ Kayıt Ol (signUp)
    ↓
Dashboard
  └─ Sensör verilerini göster (gelecekte)
  └─ Çıkış Yap (signOut)
```

---

## ⚡ Realtime (Anlık Veri) Kurulumu

1. Supabase Dashboard → **SQL Editor**
2. Proje kökündeki `supabase/realtime_setup.sql` dosyasının tamamını yapıştırıp **Run** deyin
3. Dashboard → **Database** → **Replication** bölümünde şu tabloların Realtime açık olduğunu doğrulayın:
   - `latest_sensor_status`
   - `latest_ppe_status`
   - `sensor_data`
4. Yönetici paneli için kendi e-postanıza admin yetkisi verin:

```sql
UPDATE public.profiles
SET is_admin = TRUE
WHERE user_id = (
  SELECT id FROM auth.users WHERE email = 'yonetici@firma.com'
);
```

5. `python mobil.py` çalışırken ESP32 `/upload` ile veri gönderin — Flutter ve `panel.html` **saniyesiz** güncellenir.

| Uygulama | Realtime kaynağı |
|----------|------------------|
| Flutter (işçi) | `latest_sensor_status` + `latest_ppe_status` stream |
| Web panel (yönetici) | Supabase `postgres_changes` + admin girişi |

---

## 🚀 Gelecekteki Adımlar

### 1. Sensör Veri İşleme
Tablolar oluşturduktan sonra `sensor_service.dart` güncelle:

```dart
import 'package:supabase_flutter/supabase_flutter.dart';

class SensorService {
  final _supabase = Supabase.instance.client;

  // Sensör verilerini kaydet
  Future<void> saveSensorReading({
    required double temperature,
    required double humidity,
    required int heartRate,
    required int gasLevel,
  }) async {
    try {
      await _supabase.from('sensor_readings').insert({
        'user_id': _supabase.auth.currentUser!.id,
        'temperature': temperature,
        'humidity': humidity,
        'heart_rate': heartRate,
        'gas_level': gasLevel,
      });
    } catch (e) {
      print('Error saving sensor data: $e');
    }
  }

  // Real-time sensör verilerini dinle
  Stream<List<Map<String, dynamic>>> getSensorReadings() {
    return _supabase
        .from('sensor_readings')
        .stream(primaryKey: ['id'])
        .eq('user_id', _supabase.auth.currentUser!.id)
        .order('created_at', ascending: false)
        .limit(10);
  }
}
```

### 2. Push Notifications (Opsiyonel)
```bash
flutter pub add supabase_flutter
```

### 3. Offline Mode (Opsiyonel)
Hive veya SQLite ile local caching ekle.

---

## 🧪 Test Etme

1. **Kayıt Ol:**
   - Email: `test@example.com`
   - Şifre: `Test@1234`
   - Ad Soyad: `Test User`

2. **Giriş Yap:**
   - Aynı credentials ile giriş yap

3. **Hatalı Test:**
   - Yanlış şifre gir → Hata mesajını kontrol et

---

## ⚠️ Sık Karşılaşılan Sorunlar

| Sorun | Çözüm |
|-------|-------|
| "Invalid API key" hatası | API key'i kopyala-yapıştır, boşluk yok mu kontrol et |
| "Email not confirmed" | Supabase email verification aktif. Settings'ten deaktif et (dev) |
| Bağlantı başarısız | İnternet bağlantısını kontrol et, Supabase URL'i doğru mu kontrol et |
| Veriler kaydedilmiyor | User login mi, permissions (RLS) ayarlı mı kontrol et |

---

## 📞 Yardım & Kaynaklar

- 📖 **Supabase Docs:** https://supabase.com/docs
- 📖 **Flutter Supabase:** https://supabase.com/docs/guides/getting-started/quickstarts/flutter
- 💬 **Supabase Community:** https://discord.gg/erZssBC

---

**Hazırlanma Tarihi:** 14 Mayıs 2026
**Proje:** Flutter Sensor App + Supabase
