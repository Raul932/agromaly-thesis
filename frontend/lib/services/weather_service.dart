import 'dart:convert';
import '../core/api_client.dart';
import '../models/forecast.dart';

class WeatherService {
  /// Fetch the 7-day forecast for a parcel.
  static Future<Forecast> getForecast(String parcelId) async {
    final response = await ApiClient.get('/parcels/$parcelId/forecast');
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return Forecast.fromJson(data);
    }
    throw Exception('Nu am putut încărca prognoza (${response.statusCode})');
  }

  /// Generate AI field-operations advice for the coming week.
  static Future<String> getWeeklyAdvice(String parcelId) async {
    final response = await ApiClient.post(
      '/parcels/$parcelId/weekly-advice',
      body: {},
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return data['answer'] as String;
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    throw Exception(
        data['detail'] ?? 'Eroare la serviciul AI (${response.statusCode})');
  }
}
