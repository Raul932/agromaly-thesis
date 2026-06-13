import 'dart:convert';
import '../core/api_client.dart';
import '../models/alert.dart';

class AlertService {
  /// Fetch alerts for the current user.
  static Future<List<Alert>> getAlerts({bool unreadOnly = false}) async {
    final query = unreadOnly ? '?unread_only=true' : '';
    final response = await ApiClient.get('/alerts$query');

    if (response.statusCode == 200) {
      final list = jsonDecode(response.body) as List<dynamic>;
      return list
          .map((e) => Alert.fromJson(e as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to load alerts (${response.statusCode})');
    }
  }

  /// Get unread alert count (badge).
  static Future<int> getUnreadCount() async {
    final response = await ApiClient.get('/alerts/unread-count');
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['count'] as int;
    }
    return 0;
  }

  /// Mark a single alert as read.
  static Future<void> markAsRead(String alertId) async {
    await ApiClient.patch('/alerts/$alertId/read', body: {});
  }

  /// Mark all alerts as read.
  static Future<int> markAllAsRead() async {
    final response = await ApiClient.post('/alerts/read-all', body: {});
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['count'] as int;
    }
    return 0;
  }

  /// Fetch the most recent alerts for a specific parcel.
  static Future<List<Alert>> getParcelAlerts(
    String parcelId, {
    int limit = 10,
  }) async {
    final response =
        await ApiClient.get('/parcels/$parcelId/alerts?limit=$limit');
    if (response.statusCode == 200) {
      final list = jsonDecode(response.body) as List<dynamic>;
      return list
          .map((e) => Alert.fromJson(e as Map<String, dynamic>))
          .toList();
    } else if (response.statusCode == 404) {
      return [];
    } else {
      throw Exception(
          'Failed to load parcel alerts (${response.statusCode})');
    }
  }

  /// Scan all user parcels for anomalies and create alerts.
  /// Returns {'parcels_analyzed': int, 'anomalies_found': int}.
  static Future<Map<String, int>> scanAllParcels() async {
    final response = await ApiClient.post('/alerts/scan-all', body: {});
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return {
        'parcels_analyzed': data['parcels_analyzed'] as int,
        'anomalies_found': data['anomalies_found'] as int,
      };
    }
    final err = jsonDecode(response.body) as Map<String, dynamic>;
    throw Exception(
        err['detail'] ?? 'Eroare la scanare (${response.statusCode})');
  }

  /// Generate an on-demand RAG recommendation for a parcel.
  /// Returns the recommendation text (3-paragraph AI analysis).
  /// Throws an Exception with a user-readable message on failure.
  static Future<String> generateAiRecommendation(String parcelId) async {
    final response = await ApiClient.post(
      '/parcels/$parcelId/ai-recommendation',
      body: {},
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['answer'] as String;
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    throw Exception(
        data['detail'] ?? 'AI service error (${response.statusCode})');
  }
}
