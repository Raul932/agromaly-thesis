import 'dart:convert';
import '../core/api_client.dart';
import '../models/analysis.dart';

/// Service for fetching AI anomaly analysis results.
class AnalysisApiService {
  /// Fetch anomaly analysis for a specific parcel.
  Future<Analysis> fetchAnalysis(String parcelId) async {
    final response = await ApiClient.get('/parcels/$parcelId/analysis');

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return Analysis.fromJson(data);
    } else if (response.statusCode == 401) {
      throw Exception('Session expired. Please login again.');
    } else if (response.statusCode == 404) {
      throw Exception('Parcel not found.');
    } else {
      throw Exception(
        'Failed to load analysis (${response.statusCode}).',
      );
    }
  }
}
