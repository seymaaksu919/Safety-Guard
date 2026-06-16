import 'package:flutter/foundation.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class AuthService {
  static final AuthService _instance = AuthService._internal();
  final _supabase = Supabase.instance.client;

  factory AuthService() {
    return _instance;
  }

  AuthService._internal();

  // Mevcut oturum kontrolü
  Session? get currentSession => _supabase.auth.currentSession;
  User? get currentUser => _supabase.auth.currentUser;

  /// Web dashboard'da gercek isim gorunsun diye profiles tablosuna yazar.
  Future<void> syncProfileToSupabase({String? fullName, String? email}) async {
    final user = currentUser;
    if (user == null) return;

    final name = (fullName ??
            user.userMetadata?['full_name']?.toString() ??
            '')
        .trim();
    final mail = (email ?? user.email ?? '').trim();

    try {
      await _supabase.from('profiles').upsert({
        'id': user.id,
        'full_name': name,
        'username': mail,
      });
    } catch (e) {
      // profiles tablosu / RLS yoksa uygulama yine calisir
      debugPrint('profiles sync: $e');
    }
  }

  // Giriş Yapma
  Future<AuthResponse> signIn({
    required String email,
    required String password,
  }) async {
    try {
      final response = await _supabase.auth.signInWithPassword(
        email: email,
        password: password,
      );
      await syncProfileToSupabase(email: email);
      return response;
    } on AuthException catch (e) {
      throw _handleAuthException(e);
    }
  }

  // Kaydı Yapma
  Future<AuthResponse> signUp({
    required String email,
    required String password,
    required String fullName,
  }) async {
    try {
      final response = await _supabase.auth.signUp(
        email: email,
        password: password,
        data: {'full_name': fullName},
      );
      await syncProfileToSupabase(fullName: fullName, email: email);
      return response;
    } on AuthException catch (e) {
      throw _handleAuthException(e);
    }
  }

  // Çıkış Yapma
  Future<void> signOut() async {
    try {
      await _supabase.auth.signOut();
    } on AuthException catch (e) {
      throw _handleAuthException(e);
    }
  }

  // Hata Mesajlarını Türkçeleştirme
  String _handleAuthException(AuthException e) {
    final message = e.message.toLowerCase();

    if (message.contains('invalid login credentials')) {
      return 'E-posta veya şifre hatalı. Lütfen kontrol edin.';
    } else if (message.contains('email not confirmed')) {
      return 'Lütfen e-posta adresinizi doğrulayın.';
    } else if (message.contains('user already registered')) {
      return 'Bu e-posta adresi zaten kayıtlı.';
    } else if (message.contains('password')) {
      return 'Şifre en az 6 karakter olmalıdır.';
    } else if (message.contains('email')) {
      return 'Geçerli bir e-posta adresi girin.';
    }

    return e.message;
  }
}
