import 'dart:async';
import 'package:flutter/material.dart';
import 'services/auth_service.dart';
import 'auth_screen.dart';
import 'dashboard_screen.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> with TickerProviderStateMixin {
  late AnimationController _mainController;
  late Animation<double> _pulseAnimation;
  final _authService = AuthService();

  @override
  void initState() {
    super.initState();

    // 1. Logo Nabız (Pulse) Animasyonu
    _mainController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);

    _pulseAnimation = Tween<double>(begin: 1.0, end: 1.15).animate(
      CurvedAnimation(parent: _mainController, curve: Curves.easeInOut),
    );

    // 2. Oturum Kontrolü ve Yönlendirme Mantığı
    _navigateToNext();
  }

  void _navigateToNext() {
    Timer(const Duration(seconds: 4), () {
      if (mounted) {
        // AuthService üzerinden mevcut oturumu kontrol ediyoruz
        final session = _authService.currentSession;

        Widget nextScreen;
        if (session != null) {
          nextScreen =  DashboardScreen(); // Oturum varsa Ana Sayfa
        } else {
          nextScreen = const AuthScreen(); // Oturum yoksa Giriş Ekranı
        }

        // Yumuşak bir geçiş efekti ile yönlendirme
        Navigator.pushReplacement(
          context,
          PageRouteBuilder(
            pageBuilder: (context, anim, secondAnim) => nextScreen,
            transitionsBuilder: (context, anim, secondAnim, child) {
              return FadeTransition(opacity: anim, child: child);
            },
            transitionDuration: const Duration(milliseconds: 1000),
          ),
        );
      }
    });
  }

  @override
  void dispose() {
    _mainController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        width: double.infinity,
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF1E88E5), Color(0xFF0D47A1)],
          ),
        ),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Animasyonlu Güvenlik Simgesi
            ScaleTransition(
              scale: _pulseAnimation,
              child: Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.white.withOpacity(0.1),
                ),
                child: const Icon(
                  Icons.health_and_safety,
                  size: 100,
                  color: Colors.white,
                ),
              ),
            ),
            const SizedBox(height: 40),
            // Başlıklar
            const Text(
              "SAFETY GUARD",
              style: TextStyle(
                color: Colors.white,
                fontSize: 34,
                fontWeight: FontWeight.bold,
                letterSpacing: 3,
              ),
            ),
            const Text(
              "Gerçek Zamanlı İSG Takip Sistemi",
              style: TextStyle(
                color: Colors.white70,
                fontSize: 16,
                letterSpacing: 1.2,
              ),
            ),
            const SizedBox(height: 60),
            // Sensör İkonları
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _sensorIcon(Icons.favorite, "Kalp Atışı"),
                _sensorIcon(Icons.thermostat, "Sıcaklık"),
                _sensorIcon(Icons.air, "Gaz"),
                _sensorIcon(Icons.water_drop, "Nem"),
              ],
            ),
            const SizedBox(height: 80),
            const CircularProgressIndicator(
              color: Colors.white,
              strokeWidth: 3,
            ),
          ],
        ),
      ),
    );
  }

  Widget _sensorIcon(IconData icon, String label) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 15),
      child: Column(
        children: [
          Icon(icon, color: Colors.white54, size: 30),
          const SizedBox(height: 8),
          Text(
            label,
            style: const TextStyle(color: Colors.white54, fontSize: 10),
          ),
        ],
      ),
    );
  }
}