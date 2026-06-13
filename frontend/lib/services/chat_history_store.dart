import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

/// Persists AI chat conversations locally on the device using SharedPreferences.
///
/// Each conversation is stored as a JSON array of message maps under a key:
///   - global chat → [globalKey]
///   - per-parcel chat → [parcelKey(parcelId)]
class ChatHistoryStore {
  static const String globalKey = 'chat_history_global';

  static String parcelKey(String parcelId) => 'chat_history_parcel_$parcelId';

  /// Save the full message list for a conversation.
  static Future<void> save(
    String key,
    List<Map<String, dynamic>> messages,
  ) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(key, jsonEncode(messages));
  }

  /// Load a saved conversation, or an empty list if none exists.
  static Future<List<Map<String, dynamic>>> load(String key) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(key);
    if (raw == null || raw.isEmpty) return [];
    try {
      final decoded = jsonDecode(raw) as List<dynamic>;
      return decoded.map((e) => (e as Map).cast<String, dynamic>()).toList();
    } catch (_) {
      return [];
    }
  }

  /// Delete a saved conversation.
  static Future<void> clear(String key) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(key);
  }
}
