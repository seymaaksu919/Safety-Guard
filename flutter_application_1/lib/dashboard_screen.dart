import 'package:flutter/material.dart';
import 'dart:convert';
import 'dart:async';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:supabase_flutter/supabase_flutter.dart';
import 'services/auth_service.dart';
import 'services/google_speech_service.dart';
import 'auth_screen.dart';

class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key});

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  final _authService = AuthService();
  int _selectedIndex = 0;

  // --- ESP32 -> Flask (anlik) + Supabase (kayit) ---
  static const String _esp32SupabaseUserId =
      '5757a1d7-b497-4b66-b5d1-2a72e3261a73';
  static const String _sensorApiBase = 'http://10.0.2.2:5000';
  Timer? _sensorPollTimer;
  Timer? _sensorFlaskTimer;
  RealtimeChannel? _sensorRealtimeChannel;
  Timer? _flaskTimer;
  Timer? _ppeFrameTimer;
  Uint8List? _ppeCameraFrame;
  bool _ppeFrameLoading = false;

  // --- PPE — run_ppe_flask.py port 5002 (api_mobil 5000 ile karismaz) ---
  static const String _ppeApiBase = 'http://10.0.2.2:5002';
  late final GoogleSpeechService _speechService =
      GoogleSpeechService(serverBases: [_ppeApiBase]);
  bool _voiceEnabled = true;
  Timer? _ppeVoiceTimer;
  static const Duration _ppeVoiceEvery = Duration(seconds: 10);
  /// false = ses sadece PC'de (run_ppe_flask). true = telefon da 10 sn'de bir okur.
  static const bool _soundOnPhone = false;
  bool _isPersonDetected = false;
  List<String> _missingPpeList = [];
  bool _warnHardhat = false;
  bool _warnVest = false;
  bool _warnMask = false;
  bool _isLoadingFlask = false;
  bool _ppeServerOnline = false;
  int _ppeFetchFailures = 0;
  Map<String, dynamic>? _lastGoodPpeRow;

  Map<String, dynamic>? _supabaseData;
  bool _isLoadingSupabase = true;
  String _supabaseError = '';
  String _userFullName = "Yükleniyor...";

  @override
  void initState() {
    super.initState();
    // PPE: flask kapali olsa bile kartlar hemen gorunsun
    _ppeServerOnline = false;
    _isLoadingFlask = false;
    _getUserProfile();
    _startSensorLive();
    _startPpeFromFlask();
    _startPpeCameraFeed();
    _startPpePhoneVoiceTimer();
  }

  void _clearPpeLiveState() {
    _isPersonDetected = false;
    _missingPpeList = [];
    _warnHardhat = false;
    _warnVest = false;
    _warnMask = false;
  }

  @override
  void dispose() {
    _sensorPollTimer?.cancel();
    _sensorFlaskTimer?.cancel();
    _sensorRealtimeChannel?.unsubscribe();
    _flaskTimer?.cancel();
    _ppeFrameTimer?.cancel();
    _ppeVoiceTimer?.cancel();
    _speechService.dispose();
    super.dispose();
  }

  void _startPpePhoneVoiceTimer() {
    if (!_soundOnPhone) return;
    _ppeVoiceTimer?.cancel();
    _ppeVoiceTimer = Timer.periodic(_ppeVoiceEvery, (_) {
      if (!_voiceEnabled || !_isPersonDetected || _selectedIndex != 1) return;
      final msg = _currentPpeSpeechMessage();
      if (msg.isNotEmpty) _speechService.speak(msg);
    });
  }

  String _currentPpeSpeechMessage() {
    if (!_isPersonDetected) return '';
    if (_missingPpeList.isEmpty) {
      return 'Ekipmanlar tamam. İyi çalışmalar.';
    }
    return 'Koruyucu ekipman eksik. Lütfen takın.';
  }

  static String _ppeAlertLine(String name) => '$name yok. Lütfen $name takın.';

  void _applySensorData(Map<String, dynamic> data) {
    if (!mounted) return;
    setState(() {
      _supabaseData = data;
      _isLoadingSupabase = false;
      _supabaseError = '';
    });
  }

  bool _boolField(Map<String, dynamic> row, String key) {
    final v = row[key];
    return v == true || v?.toString() == 'true';
  }

  void _applyPpeData(Map<String, dynamic> row) {
    final warnHardhat = _boolField(row, 'hardhat_warning');
    final warnVest = _boolField(row, 'safety_vest_warning');
    final warnMask = _boolField(row, 'mask_warning');

    final missing = <String>[];
    if (warnHardhat) missing.add('Kask');
    if (warnVest) missing.add('Yelek');
    if (warnMask) missing.add('Maske');

    final person = _boolField(row, 'person_detected');

    final displayFp =
        '$person|$warnHardhat|$warnVest|$warnMask';
    final unchanged = !_isLoadingFlask &&
        displayFp ==
            '$_isPersonDetected|$_warnHardhat|$_warnVest|$_warnMask';
    if (unchanged) return;

    if (!mounted) return;

    setState(() {
      _isPersonDetected = person;
      _missingPpeList = missing;
      _warnHardhat = warnHardhat;
      _warnVest = warnVest;
      _warnMask = warnMask;
      _isLoadingFlask = false;
      _ppeServerOnline = true;
    });

    // Ses PC'de (run_ppe_flask). Telefon sesi kapali (_soundOnPhone=false).
  }

  // SUPABASE'DEN KULLANICININ GERÇEK ADINI ÇEKEN FONKSİYON
  Future<void> _getUserProfile() async {
    try {
      final currentUser = Supabase.instance.client.auth.currentUser;
      if (currentUser != null) {
        final fullName = currentUser.userMetadata?['full_name'];
        
        if (mounted && fullName != null) {
          setState(() {
            _userFullName = fullName.toString();
          });
        } else {
          final emailPrefix = currentUser.email?.split('@')[0] ?? "Kullanıcı";
          setState(() {
            _userFullName = emailPrefix;
          });
        }
      }
    } catch (e) {
      debugPrint("Kullanıcı adı çekilemedi: $e");
    }
  }

  Future<void> _startSensorLive() async {
    final currentUser = Supabase.instance.client.auth.currentUser;

    if (currentUser == null) {
      setState(() {
        _supabaseError = 'Lutfen giris yapin.';
        _isLoadingSupabase = false;
      });
      return;
    }

    _startSensorFromFlask();
    _subscribeSensorRealtime(currentUser.id);
    await _fetchLatestFromSensorData(currentUser.id);

    _sensorPollTimer = Timer.periodic(const Duration(seconds: 8), (_) {
      _fetchLatestFromSensorData(currentUser.id);
    });
  }

  void _startSensorFromFlask() {
    _fetchSensorFromFlask();
    _sensorFlaskTimer = Timer.periodic(const Duration(milliseconds: 900), (_) {
      _fetchSensorFromFlask();
    });
  }

  Future<void> _fetchSensorFromFlask() async {
    try {
      final response = await http
          .get(Uri.parse('$_sensorApiBase/api/status'))
          .timeout(const Duration(seconds: 2));
      if (response.statusCode != 200 || !mounted) return;

      final data = jsonDecode(response.body) as Map<String, dynamic>;
      _applySensorData(data);
    } catch (e) {
      debugPrint('Flask sensor okuma: $e');
    }
  }

  void _subscribeSensorRealtime(String userId) {
    final listenId =
        userId == _esp32SupabaseUserId ? userId : _esp32SupabaseUserId;

    _sensorRealtimeChannel?.unsubscribe();
    _sensorRealtimeChannel = Supabase.instance.client
        .channel('sensor_live_$listenId')
        .onPostgresChanges(
          event: PostgresChangeEvent.insert,
          schema: 'public',
          table: 'sensor_data',
          filter: PostgresChangeFilter(
            type: PostgresChangeFilterType.eq,
            column: 'user_id',
            value: listenId,
          ),
          callback: (payload) {
            final row = payload.newRecord;
            if (row.isEmpty || !mounted) return;
            _applySensorData(Map<String, dynamic>.from(row));
          },
        )
        .subscribe();
  }

  Future<void> _fetchLatestFromSensorData(String userId) async {
    try {
      final history = await Supabase.instance.client
          .from('sensor_data')
          .select()
          .eq('user_id', userId)
          .order('created_at', ascending: false)
          .limit(1);

      if (!mounted) return;

      if (history.isNotEmpty) {
        _applySensorData(Map<String, dynamic>.from(history.first));
        return;
      }

      if (userId != _esp32SupabaseUserId) {
        final espRows = await Supabase.instance.client
            .from('sensor_data')
            .select()
            .eq('user_id', _esp32SupabaseUserId)
            .order('created_at', ascending: false)
            .limit(1);
        if (!mounted) return;
        if (espRows.isNotEmpty) {
          setState(() {
            _supabaseError =
                'Veriler baska hesaba yaziliyor.\n\n'
                'Giris ID:\n$userId\n\n'
                'ESP32 yazdigi ID:\n$_esp32SupabaseUserId\n\n'
                'Cozum: api_mobil.py DEFAULT_USER_ID guncelleyin.';
            _isLoadingSupabase = false;
          });
          return;
        }
      }

      if (!mounted) return;
      setState(() {
        _supabaseError =
            'Henuz veri yok.\n\n'
            '1) python api_mobil.py\n'
            '2) ESP32 POST /upload\n\n'
            'Giris ID:\n$userId';
        _isLoadingSupabase = false;
      });
    } catch (e) {
      debugPrint('sensor_data okuma hatasi: $e');
      if (mounted) {
        setState(() {
          _supabaseError = 'Supabase okuma hatasi:\n$e';
          _isLoadingSupabase = false;
        });
      }
    }
  }

  void _startPpeCameraFeed() {
    _ppeFrameTimer?.cancel();
    _fetchPpeCameraFrame();
    _ppeFrameTimer = Timer.periodic(const Duration(milliseconds: 450), (_) {
      if (_selectedIndex == 1) _fetchPpeCameraFrame();
    });
  }

  Future<void> _fetchPpeCameraFrame() async {
    if (_ppeFrameLoading) return;
    _ppeFrameLoading = true;
    try {
      final uri = Uri.parse(
        '$_ppeApiBase/api/frame?_=${DateTime.now().millisecondsSinceEpoch}',
      );
      final res = await http
          .get(uri)
          .timeout(const Duration(seconds: 4));
      if (res.statusCode == 200 && mounted) {
        setState(() => _ppeCameraFrame = res.bodyBytes);
      }
    } catch (e) {
      debugPrint('PPE kamera karesi: $e');
    } finally {
      _ppeFrameLoading = false;
    }
  }

  // PPE — run_ppe_flask.py -> /api/status veya /api/ppe/<id>
  void _startPpeFromFlask() {
    _fetchPpeStatus();
    _flaskTimer = Timer.periodic(const Duration(milliseconds: 1200), (_) {
      _fetchPpeStatus();
    });
  }

  Future<void> _fetchPpeStatus() async {
    final userId = Supabase.instance.client.auth.currentUser?.id ?? '';
    final urls = <String>[
      '$_ppeApiBase/api/status',
      if (userId.isNotEmpty) '$_ppeApiBase/api/ppe/$userId',
    ];

    Object? lastError;
    for (final url in urls) {
      try {
        final response = await http
            .get(Uri.parse(url))
            .timeout(const Duration(seconds: 4));
        if (!mounted) return;

        if (response.statusCode == 200) {
          final row = Map<String, dynamic>.from(jsonDecode(response.body) as Map);
          _ppeFetchFailures = 0;
          _lastGoodPpeRow = row;
          _applyPpeData(row);
          if (_selectedIndex == 1) _fetchPpeCameraFrame();
          return;
        }
        lastError = 'HTTP ${response.statusCode} @ $url';
      } catch (e) {
        lastError = e;
        debugPrint('PPE API ($url): $e');
      }
    }

    if (!mounted) return;
    _ppeFetchFailures++;
    debugPrint('PPE offline (port 5002): $lastError');

    // Son iyi veri varsa kisa sure koru; yoksa hemen offline kartlar
    if (_lastGoodPpeRow != null && _ppeFetchFailures < 3) {
      return;
    }

    setState(() {
      _ppeServerOnline = false;
      _isLoadingFlask = false;
      _clearPpeLiveState();
    });
  }

  Future<void> _signOut(BuildContext context) async {
    await _authService.signOut();
    if (mounted) {
      Navigator.pushReplacement(
        context,
        MaterialPageRoute(builder: (context) => const AuthScreen()),
      );
    }
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
          child: _selectedIndex == 0 ? _buildDashboardPage() : _buildPpeStatusPage(),
        ),
      ),
      bottomNavigationBar: _buildBottomNav(),
    );
  }

  Widget _buildDashboardPage() {
    return Column(
      children: [
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              children: [
                _buildTopBar(context),
                const SizedBox(height: 12),
                _buildSensorDataContent(),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildSensorDataContent() {
    if (_supabaseError.isNotEmpty) return _errorWidget(_supabaseError);
    if (_isLoadingSupabase || _supabaseData == null) {
      return const Center(child: CircularProgressIndicator(color: Colors.white));
    }

    final data = _supabaseData!;
    final double bpm =
        double.tryParse(data['heart_rate']?.toString() ?? '0') ?? 0.0;
    final double bodyTemp =
        double.tryParse(data['body_temp']?.toString() ?? '0') ?? 0.0;
    final double ambientTemp =
        double.tryParse(data['ambient_temp']?.toString() ?? '0') ?? 0.0;
    final double humidity =
        double.tryParse(data['humidity']?.toString() ?? '0') ?? 0.0;
    final double gasPercent = double.tryParse(
            (data['gas_percent'] ?? data['gas_level'])?.toString() ?? '0') ??
        0.0;
    final double gasPercent2 = double.tryParse(
            (data['gas_percent2'] ?? data['gas_level2'])?.toString() ?? '0') ??
        0.0;
    final bool fireRisk =
        data['flame'] == true || data['flame']?.toString() == 'true';
    final String systemStatus = data['status']?.toString() ?? 'SAFE';

    Color statusColor = Colors.green.shade700;
    if (systemStatus == 'WARNING') statusColor = Colors.orange.shade700;
    if (systemStatus == 'CRITICAL' || systemStatus == 'FIRE DETECTED') {
      statusColor = Colors.red.shade800;
    }

    return Column(
      children: [
        _buildFireRiskPanel(fireRisk),
        const SizedBox(height: 12),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: statusColor,
            borderRadius: BorderRadius.circular(20),
            boxShadow: const [BoxShadow(color: Colors.black26, blurRadius: 6)],
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'SİSTEM ANALİZİ',
                style: TextStyle(
                  color: Colors.white70,
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                'DURUM: $systemStatus',
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 15),
        GridView.count(
          crossAxisCount: 2,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisSpacing: 12,
          mainAxisSpacing: 12,
          childAspectRatio: 1.1,
          children: [
            _buildValueCard(
              'Nabız',
              '${bpm.toInt()} BPM',
              Icons.favorite,
              bpm > 120 ? Colors.red : Colors.redAccent,
            ),
            _buildValueCard(
              'Vücut Isısı',
              '${bodyTemp.toStringAsFixed(1)}°C',
              Icons.accessibility_new,
              bodyTemp > 37.5 ? Colors.red : Colors.orange,
            ),
            _buildValueCard(
              'Ortam Sıcaklığı',
              '${ambientTemp.toStringAsFixed(1)}°C',
              Icons.thermostat,
              Colors.teal,
            ),
            _buildValueCard(
              'Nem Oranı',
              '%${humidity.toInt()}',
              Icons.water_drop,
              Colors.blue,
            ),
            _buildValueCard(
              'Hava Kalitesi',
              '%${gasPercent.toStringAsFixed(1)}',
              Icons.air,
              gasPercent > 50.0 ? Colors.red : Colors.green,
            ),
            _buildValueCard(
              'Gaz Seviyesi',
              '%${gasPercent2.toStringAsFixed(1)}',
              Icons.gas_meter,
              gasPercent2 > 50.0 ? Colors.red : Colors.purple,
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildPpeStatusPage() {
    return Column(
      children: [
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              children: [
                _buildTopBar(context),
                const SizedBox(height: 12),
                _buildFlaskPpeContent(),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildFlaskPpeContent() {
    final online = _ppeServerOnline;
    final personVisible = online && _isPersonDetected;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Ortam izleme',
          style: TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 8),
        _buildPpeCameraPanel(online: online),
        const SizedBox(height: 18),
        const Text(
          'Kişisel Ekipman Durumu',
          style: TextStyle(
            color: Colors.white,
            fontSize: 18,
            fontWeight: FontWeight.bold,
          ),
        ),
        const SizedBox(height: 16),
        _buildPpeItemCard(
          name: 'İşçi algılama',
          icon: online
              ? (_isPersonDetected ? Icons.person : Icons.person_off)
              : Icons.cloud_off,
          ppeServerOnline: online,
          personVisible: personVisible,
          hasWarning: false,
        ),
        const SizedBox(height: 12),
        _buildPpeItemCard(
          name: 'Kask',
          icon: Icons.construction,
          ppeServerOnline: online,
          personVisible: personVisible,
          hasWarning: _warnHardhat,
        ),
        const SizedBox(height: 10),
        _buildPpeItemCard(
          name: 'Yelek',
          icon: Icons.checkroom,
          ppeServerOnline: online,
          personVisible: personVisible,
          hasWarning: _warnVest,
        ),
        const SizedBox(height: 10),
        _buildPpeItemCard(
          name: 'Maske',
          icon: Icons.masks,
          ppeServerOnline: online,
          personVisible: personVisible,
          hasWarning: _warnMask,
        ),
      ],
    );
  }

  Widget _buildPpeCameraPanel({required bool online}) {
    final hasImage = _ppeCameraFrame != null && _ppeCameraFrame!.isNotEmpty;

    String subtitle;
    if (!online) {
      subtitle = 'run_ppe_flask.py çalıştırın (port 5002)';
    } else if (!hasImage) {
      subtitle = 'Kamera bağlanıyor…';
    } else {
      subtitle = 'YOLO işaretlemeli canlı görüntü';
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: double.infinity,
          height: 220,
          decoration: BoxDecoration(
            color: Colors.black87,
            borderRadius: BorderRadius.circular(20),
            boxShadow: const [
              BoxShadow(color: Colors.black26, blurRadius: 8, offset: Offset(0, 4)),
            ],
            border: Border.all(
              color: online ? Colors.white24 : Colors.white12,
              width: 1,
            ),
          ),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(20),
            child: hasImage
                ? Image.memory(
                    _ppeCameraFrame!,
                    fit: BoxFit.cover,
                    width: double.infinity,
                    height: double.infinity,
                    gaplessPlayback: true,
                    filterQuality: FilterQuality.medium,
                  )
                : Center(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          online ? Icons.videocam : Icons.videocam_off,
                          color: Colors.white54,
                          size: 48,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          subtitle,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Colors.white70,
                            fontSize: 13,
                          ),
                        ),
                      ],
                    ),
                  ),
          ),
        ),
        const SizedBox(height: 6),
        Row(
          children: [
            Icon(
              online ? Icons.circle : Icons.circle_outlined,
              size: 10,
              color: online ? Colors.lightGreenAccent : Colors.white38,
            ),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                subtitle,
                style: const TextStyle(color: Colors.white70, fontSize: 12),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildTopBar(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        Text(
          _userFullName, 
          style: const TextStyle(
            color: Colors.white, 
            fontWeight: FontWeight.bold,
            fontSize: 15,
          ),
        ),
        if (_selectedIndex == 1)
          IconButton(
            tooltip: _voiceEnabled ? 'Sesi kapat' : 'Sesi aç',
            onPressed: () => setState(() {
              _voiceEnabled = !_voiceEnabled;
              _speechService.enabled = _voiceEnabled;
            }),
            icon: Icon(
              _voiceEnabled ? Icons.volume_up : Icons.volume_off,
              color: Colors.white70,
            ),
          ),
        IconButton(
          onPressed: () => _signOut(context), 
          icon: const Icon(Icons.logout, color: Colors.white70),
        ),
      ],
    );
  }

  Widget _buildFireRiskPanel(bool hasRisk) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: hasRisk ? Colors.red.shade800 : Colors.green.shade700,
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [BoxShadow(color: Colors.black, blurRadius: 8)],
      ),
      child: Row(
        children: [
          Icon(hasRisk ? Icons.local_fire_department : Icons.gpp_good, color: Colors.white, size: 30),
          const SizedBox(width: 15),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text("YANGIN RİSK DURUMU", style: TextStyle(color: Colors.white70, fontSize: 11, fontWeight: FontWeight.bold)),
                const SizedBox(height: 2),
                Text(
                  hasRisk ? "TEHLİKE: YANGIN VEYA ALEV ALGILANDI!" : "GÜVENLİ: Yangın Riski Tespit Edilmedi.",
                  style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildValueCard(String title, String value, IconData icon, Color color) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 6)],
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, color: color, size: 30),
          const SizedBox(height: 8),
          Text(title, style: TextStyle(color: Colors.grey[600], fontSize: 11, fontWeight: FontWeight.w500), textAlign: TextAlign.center),
          const SizedBox(height: 2),
          Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF0D47A1)), textAlign: TextAlign.center),
        ],
      ),
    );
  }

  /// Her ekipman icin ayri beyaz kutu — flask kapali olsa bile gosterilir.
  Widget _buildPpeItemCard({
    required String name,
    required IconData icon,
    required bool ppeServerOnline,
    required bool personVisible,
    required bool hasWarning,
  }) {
    String statusLine;
    Color color;

    if (!ppeServerOnline) {
      statusLine = 'Bağlantı bekleniyor';
      color = Colors.blueGrey;
    } else if (name == 'İşçi algılama') {
      if (_isPersonDetected) {
        statusLine = 'Kişi kamerada';
        color = Colors.green;
      } else {
        statusLine = 'Kişi yok';
        color = Colors.orange;
      }
    } else if (!personVisible) {
      statusLine = 'Kontrol bekleniyor';
      color = Colors.blueGrey;
    } else if (hasWarning) {
      statusLine = _ppeAlertLine(name);
      color = Colors.red;
    } else {
      statusLine = '$name takılı ✓';
      color = Colors.green;
    }

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        boxShadow: const [BoxShadow(color: Colors.black12, blurRadius: 10)],
      ),
      child: Row(
        children: [
          Container(
            decoration: BoxDecoration(
              color: color.withOpacity(0.12),
              shape: BoxShape.circle,
            ),
            padding: const EdgeInsets.all(12),
            child: Icon(icon, color: color, size: 24),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  name,
                  style: const TextStyle(fontSize: 12, color: Colors.black54),
                ),
                const SizedBox(height: 6),
                Text(
                  statusLine,
                  style: const TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    color: Color(0xFF0D47A1),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBottomNav() {
    return BottomNavigationBar(
      currentIndex: _selectedIndex,
      onTap: (index) {
        setState(() => _selectedIndex = index);
        if (index == 1) _fetchPpeCameraFrame();
      },
      selectedItemColor: const Color(0xFF1E88E5),
      unselectedItemColor: Colors.grey,
      backgroundColor: Colors.white,
      elevation: 8,
      items: const [
        BottomNavigationBarItem(icon: Icon(Icons.bar_chart), label: 'Anasayfa'),
        BottomNavigationBarItem(icon: Icon(Icons.shield), label: 'PPE Durumu'),
      ],
    );
  }

  Widget _errorWidget(String error) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(color: Colors.red.withOpacity(0.2), borderRadius: BorderRadius.circular(20)),
      child: Text(error, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 13), textAlign: TextAlign.center),
    );
  }
} 