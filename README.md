🦺 Safety Guard AI – Endüstriyel İSG İzleme Sistemi
<p align="center"> <img src="https://img.shields.io/badge/AI-YOLOv8-blue"> <img src="https://img.shields.io/badge/IoT-ESP32-orange"> <img src="https://img.shields.io/badge/Backend-Flask-green"> <img src="https://img.shields.io/badge/Database-Supabase-lightgreen"> </p>
📌 PROJE ÖZETİ
<p> <strong>Safety Guard AI</strong>, endüstriyel üretim sahalarında iş güvenliğini sağlamak için geliştirilmiş IoT + Yapay Zeka tabanlı gerçek zamanlı bir İSG izleme sistemidir. </p> <p> Sistem; biyometrik veriler, çevresel sensörler ve kamera görüntülerini birleştirerek <span style="color:#ff4d4d;"><b>anlık risk analizi ve KKD ihlali tespiti</b></span> yapar. </p>
⚠️ Problem Tanımı
<ul> <li>Periyodik kontroller gerçek zamanlı riskleri yakalayamaz</li> <li>KKD (baret, yelek, maske) ihlalleri geç fark edilir</li> <li>Gaz, sıcaklık ve yangın riskleri anlık izlenmez</li> </ul>
🏗 Sistem Mimarisi
<table> <tr> <td><b>Katman</b></td> <td><b>Teknoloji</b></td> </tr> <tr> <td>Donanım</td> <td>ESP32, ESP32-CAM, PPG sensör, NTC, MQ-135, MQ-8, DHT11</td> </tr> <tr> <td>AI Model</td> <td>YOLOv8s (KKD tespiti)</td> </tr> <tr> <td>Backend</td> <td>Flask API + Risk Engine</td> </tr> <tr> <td>Database</td> <td>Supabase (PostgreSQL + Realtime)</td> </tr> <tr> <td>Frontend</td> <td>Flutter + Web Dashboard</td> </tr> </table>
🧠 Yapay Zeka (YOLOv8)
<ul> <li>Baret tespiti</li> <li>Yelek kontrolü</li> <li>Maske denetimi</li> </ul> <p> <b>Model doğruluğu:</b> %91.4 mAP@50 </p>
🔌 Donanım Tasarımı (Özgün Katkı)
<ul> <li>PPG nabız ölçüm devresi (LM324 filtreleme)</li> <li>NTC sıcaklık ölçüm devresi (buffer op-amp)</li> <li>Endüstriyel gürültü filtreleme optimizasyonu</li> </ul>
🚨 Risk Engine
<pre> Risk Score = f(biyometrik_veri, çevresel_veri, KKD_ihlali, zaman) </pre> <ul> <li>Kritik eşik → otomatik alarm</li> <li>Çoklu sensör doğrulama → false positive azaltma</li> </ul>
🚀 Özellikler
<ul> <li>Gerçek zamanlı KKD tespiti</li> <li>100ms altı veri akışı</li> <li>IoT + AI sensör füzyonu</li> <li>API key + timestamp güvenlik sistemi</li> <li>Modüler endüstriyel yapı</li> </ul>
📊 Performans
<table> <tr> <td><b>Metrik</b></td> <td><b>Sonuç</b></td> </tr> <tr> <td>KKD Doğruluk</td> <td>%91.4 mAP@50</td> </tr> <tr> <td>Gecikme</td> <td>&lt; 100 ms</td> </tr> <tr> <td>Sinyal Stabilitesi</td> <td>Yüksek (endüstriyel ortam testli)</td> </tr> </table>
📁 Proje Yapısı
<pre> Safety-Guard-AI/ │ ├── backend/ ├── ai_model/ ├── iot/ ├── mobile_app/ ├── dashboard/ └── requirements.txt </pre>
⭐ Öne Çıkan Güçlü Noktalar
<p> ✔ Özgün analog devre tasarımı <br> ✔ YOLOv8 tabanlı gerçek zamanlı AI <br> ✔ IoT sensör füzyonu <br> ✔ Endüstriyel risk motoru </p>
🔮 Gelecek Çalışmalar
<ul> <li>Edge AI (ESP32 üzerinde model çalıştırma)</li> <li>LSTM ile risk tahmini</li> <li>Daha düşük gecikmeli streaming mimarisi</li> </ul>
