import 'dart:async';
import 'dart:convert';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:http/http.dart' as http;

/// Tek seferde tek cumle — sesler ust uste binmez.
class GoogleSpeechService {
  GoogleSpeechService({required List<String> serverBases}) : _serverBases = serverBases;

  final List<String> _serverBases;
  final AudioPlayer _player = AudioPlayer();
  final FlutterTts _tts = FlutterTts();

  bool enabled = true;
  bool _ready = false;
  bool _speaking = false;
  DateTime? _lastSpokeAt;
  static const Duration minInterval = Duration(seconds: 10);
  String? _selectedVoiceName;
  String lastStatus = '';

  void Function(String status)? onStatus;

  Future<void> _pickBestTurkishVoice() async {
    try {
      if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
        final engines = await _tts.getEngines;
        if (engines is List) {
          for (final e in engines) {
            final id = e.toString();
            if (id.contains('google')) {
              await _tts.setEngine(id);
              break;
            }
          }
        }
      }

      final voices = await _tts.getVoices;
      if (voices is! List || voices.isEmpty) {
        await _tts.setLanguage('tr-TR');
        return;
      }

      Map<dynamic, dynamic>? best;
      int bestScore = -1;

      for (final v in voices) {
        if (v is! Map) continue;
        final locale = (v['locale'] ?? '').toString().toLowerCase();
        if (!locale.startsWith('tr')) continue;

        final name = (v['name'] ?? '').toString().toLowerCase();
        var score = 10;
        if (name.contains('network')) score += 50;
        if (name.contains('neural')) score += 40;
        if (name.contains('premium')) score += 35;
        if (name.contains('google')) score += 25;

        if (score > bestScore) {
          bestScore = score;
          best = Map<dynamic, dynamic>.from(v);
        }
      }

      if (best != null) {
        await _tts.setVoice({
          'name': best['name'].toString(),
          'locale': best['locale'].toString(),
        });
        _selectedVoiceName = best['name'].toString();
        return;
      }
      await _tts.setLanguage('tr-TR');
    } catch (e) {
      await _tts.setLanguage('tr-TR');
    }
  }

  Future<void> init() async {
    if (_ready) return;
    try {
      await AudioPlayer.global.setAudioContext(
        AudioContext(
          android: AudioContextAndroid(
            isSpeakerphoneOn: true,
            contentType: AndroidContentType.speech,
            usageType: AndroidUsageType.media,
            audioFocus: AndroidAudioFocus.gain,
          ),
          iOS: AudioContextIOS(
            category: AVAudioSessionCategory.playback,
            options: {AVAudioSessionOptions.defaultToSpeaker},
          ),
        ),
      );
    } catch (_) {}

    try {
      await _tts.setVolume(1.0);
      await _tts.setSpeechRate(0.38);
      await _tts.awaitSpeakCompletion(true);
      await _pickBestTurkishVoice();
    } catch (_) {}
    _ready = true;
  }

  void _status(String msg) {
    lastStatus = msg;
    onStatus?.call(msg);
    debugPrint('🔊 $msg');
  }

  Future<void> stopAll() async {
    try {
      await _player.stop();
      await _tts.stop();
    } catch (_) {}
  }

  Future<void> _waitMp3Done() async {
    try {
      await _player.onPlayerComplete.first.timeout(const Duration(seconds: 30));
    } catch (_) {}
  }

  Future<bool> _speakTurkishMp3FromServer(String text) async {
    for (final base in _serverBases) {
      try {
        final response = await http
            .post(
              Uri.parse('$base/api/speak'),
              headers: {'Content-Type': 'application/json; charset=utf-8'},
              body: jsonEncode({'text': text}),
            )
            .timeout(const Duration(seconds: 45));

        final bytes = response.bodyBytes;
        if (response.statusCode == 200 && bytes.length > 200) {
          await _player.stop();
          await _player.setReleaseMode(ReleaseMode.stop);
          await _player.setVolume(1.0);
          await _player.play(BytesSource(bytes));
          await _waitMp3Done();
          return true;
        }
      } catch (e) {
        debugPrint('gTTS $base: $e');
      }
    }
    return false;
  }

  Future<bool> _speakOnPhone(String text) async {
    await init();
    try {
      await _tts.stop();
      final ok = await _tts.speak(text);
      return ok == 1;
    } catch (_) {
      return false;
    }
  }

  /// Ayni anda yalnizca bir uyari calar.
  Future<void> speak(String text) async {
    final trimmed = text.trim();
    if (!enabled || trimmed.isEmpty) return;

    final now = DateTime.now();
    if (_lastSpokeAt != null && now.difference(_lastSpokeAt!) < minInterval) {
      return;
    }
    if (_speaking) return;

    _lastSpokeAt = now;
    _speaking = true;

    try {
      if (await _speakTurkishMp3FromServer(trimmed)) {
        _status(trimmed);
        return;
      }
      if (await _speakOnPhone(trimmed)) {
        _status(trimmed);
        return;
      }
      _status('Ses yok — run_ppe_flask acik mi?');
    } finally {
      _speaking = false;
    }
  }

  Future<void> speakTest() async {
    await speak('Koruyucu ekipman eksik. Lütfen takın.');
  }

  Future<void> dispose() async {
    await stopAll();
    await _player.dispose();
  }
}
