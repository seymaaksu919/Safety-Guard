import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import 'splash_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Supabase bağlantı ayarları - Safety Guard projesi
  await Supabase.initialize(
    url: 'https://tsslkuwpqqvxxhuwttbk.supabase.co',
    anonKey: 'sb_publishable_9cX7xtFcc85spzMuD2XBgQ_ro1YcEJU',
  );

  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Safety Guard',
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1E88E5), // Mühendislik mavisi
          brightness: Brightness.light,
        ),
      ),
      home: const SplashScreen(), // Uygulama animasyonla başlar
    );
  }
}