import 'dart:convert';
import '../core/api_client.dart';

class ChatService {
  /// Ask a general agronomic question (global chatbot).
  static Future<String> askGlobal(
    String message,
    List<Map<String, String>> history,
  ) async {
    final response = await ApiClient.post(
      '/chat/ask',
      body: {
        'message': message,
        'history': history,
      },
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['answer'] as String;
    } else if (response.statusCode == 503) {
      throw Exception('AI service is not available. Please try again later.');
    } else {
      throw Exception('Failed to get answer (${response.statusCode})');
    }
  }

  /// Ask a question scoped to a specific parcel.
  static Future<String> askParcel(
    String parcelId,
    String message,
    List<Map<String, String>> history,
  ) async {
    final response = await ApiClient.post(
      '/chat/parcels/$parcelId/ask',
      body: {
        'message': message,
        'history': history,
      },
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['answer'] as String;
    } else if (response.statusCode == 503) {
      throw Exception('AI service is not available. Please try again later.');
    } else if (response.statusCode == 403) {
      throw Exception('You do not have access to this parcel.');
    } else {
      throw Exception('Failed to get parcel answer (${response.statusCode})');
    }
  }
}
