import 'package:flutter/material.dart';
import 'services/auth_service.dart';
import 'dashboard_screen.dart';

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _authService = AuthService();
  final TextEditingController _emailController = TextEditingController();
  final TextEditingController _passwordController = TextEditingController();
  final TextEditingController _nameController = TextEditingController();
  
  bool _isLoading = false;
  bool _isLogin = true;

  // Ana İşlem Fonksiyonu
  Future<void> _authIslemi() async {
    final email = _emailController.text.trim();
    final password = _passwordController.text.trim();
    final name = _nameController.text.trim();

    // 1. Basit alan kontrolü
    if (email.isEmpty || password.isEmpty || (!_isLogin && name.isEmpty)) {
      _mesajGoster('Lütfen tüm alanları doldurun.', hata: true);
      return;
    }

    setState(() => _isLoading = true);

    try {
      if (_isLogin) {
        // --- GİRİŞ YAPMA İŞLEMİ ---
        await _authService.signIn(
          email: email,
          password: password,
        );
      } else {
        // --- KAYIT OLMA İŞLEMİ ---
        await _authService.signUp(
          email: email,
          password: password,
          fullName: name,
        );
        _mesajGoster('Kayıt başarılı! Giriş yapılıyor...');
      }

      // BAŞARILI İSE DASHBOARD'A GİT
      if (mounted) {
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(builder: (context) => DashboardScreen()),
        );
      }
    } catch (e) {
      _mesajGoster(e.toString(), hata: true);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _mesajGoster(String mesaj, {bool hata = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Row(
          children: [
            Icon(
              hata ? Icons.error_outline : Icons.check_circle_outline,
              color: Colors.white,
            ),
            const SizedBox(width: 10),
            Expanded(child: Text(mesaj)),
          ],
        ),
        backgroundColor: hata ? Colors.redAccent : Colors.green,
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 3),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(15)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Container(
        width: double.infinity,
        height: double.infinity,
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [Color(0xFF1E88E5), Color(0xFF0D47A1)],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 30),
              physics: const BouncingScrollPhysics(),
              child: Column(
                children: [
                  const Icon(Icons.health_and_safety, size: 90, color: Colors.white),
                  const SizedBox(height: 10),
                  const Text(
                    "SAFETY GUARD",
                    style: TextStyle(
                      color: Colors.white70, 
                      fontSize: 16, 
                      letterSpacing: 2
                    ),
                  ),
                  const SizedBox(height: 40),

                  Card(
                    elevation: 15,
                    shadowColor: Colors.black45,
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(25)),
                    child: Padding(
                      padding: const EdgeInsets.all(25),
                      child: Column(
                        children: [
                          Text(
                            _isLogin ? "TEKRAR HOŞ GELDİNİZ" : "YENİ HESAP",
                            style: const TextStyle(
                              fontSize: 18, 
                              fontWeight: FontWeight.bold, 
                              color: Color(0xFF0D47A1),
                              letterSpacing: 1.2
                            ),
                          ),
                          const SizedBox(height: 25),
                          
                          if (!_isLogin) ...[
                            _buildTextField(
                              controller: _nameController,
                              label: "Ad Soyad",
                              icon: Icons.person_outline,
                            ),
                            const SizedBox(height: 15),
                          ],

                          _buildTextField(
                            controller: _emailController,
                            label: "E-posta",
                            icon: Icons.email_outlined,
                            type: TextInputType.emailAddress,
                          ),
                          const SizedBox(height: 15),

                          _buildTextField(
                            controller: _passwordController,
                            label: "Şifre",
                            icon: Icons.lock_outline,
                            isPassword: true,
                          ),
                          
                          const SizedBox(height: 30),

                          _isLoading
                              ? const CircularProgressIndicator()
                              : SizedBox(
                                  width: double.infinity,
                                  height: 55,
                                  child: ElevatedButton(
                                    onPressed: _authIslemi,
                                    style: ElevatedButton.styleFrom(
                                      backgroundColor: const Color(0xFF0D47A1),
                                      foregroundColor: Colors.white,
                                      elevation: 5,
                                      shape: RoundedRectangleBorder(
                                        borderRadius: BorderRadius.circular(15)
                                      ),
                                    ),
                                    child: Text(
                                      _isLogin ? "GİRİŞ YAP" : "KAYIT OL",
                                      style: const TextStyle(
                                        fontWeight: FontWeight.bold, 
                                        letterSpacing: 1.5
                                      ),
                                    ),
                                  ),
                                ),
                          
                          const SizedBox(height: 15),

                          TextButton(
                            onPressed: () => setState(() => _isLogin = !_isLogin),
                            child: Text(
                              _isLogin 
                                ? "Hesabınız yok mu? Hemen Katılın" 
                                : "Zaten üye misiniz? Giriş Yapın",
                              style: const TextStyle(color: Colors.blueGrey, fontSize: 13),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                  const Text(
                    "",
                    style: TextStyle(color: Colors.white54, fontSize: 10),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildTextField({
    required TextEditingController controller,
    required String label,
    required IconData icon,
    bool isPassword = false,
    TextInputType type = TextInputType.text,
  }) {
    return TextField(
      controller: controller,
      obscureText: isPassword,
      keyboardType: type,
      decoration: InputDecoration(
        prefixIcon: Icon(icon, color: const Color(0xFF1E88E5)),
        labelText: label,
        labelStyle: const TextStyle(color: Colors.blueGrey, fontSize: 14),
        filled: true,
        fillColor: Colors.grey[50],
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(15),
          borderSide: BorderSide(color: Colors.grey[200]!),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(15),
          borderSide: const BorderSide(color: Color(0xFF1E88E5), width: 2),
        ),
      ),
    );
  }
}