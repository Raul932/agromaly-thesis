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
}
