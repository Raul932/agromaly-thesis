import 'dart:convert';
import '../core/api_client.dart';
import '../models/parcel.dart';

/// Service for parcel CRUD operations against the backend.
class ParcelApiService {
  /// Fetch all parcels owned by the authenticated user.
  Future<List<Parcel>> fetchParcels() async {
    final response = await ApiClient.get('/parcels?limit=100&offset=0');

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final items = data['items'] as List<dynamic>;
      return items
          .map((json) => Parcel.fromJson(json as Map<String, dynamic>))
          .toList();
    } else if (response.statusCode == 401) {
      throw Exception('Session expired. Please login again.');
    } else {
      throw Exception('Failed to load parcels (${response.statusCode}).');
    }
  }

  /// Create a new parcel.
  ///
  /// Sends GeoJSON geometry to match the backend's ParcelCreate schema.
  Future<Parcel> createParcel({
    required String name,
    required String cropType,
    required double areaHa,
    String? description,
    required List<List<List<double>>> coordinates,
  }) async {
    final body = {
      'name': name,
      'crop_type': cropType,
      'area_ha': areaHa,
      if (description != null && description.isNotEmpty)
        'description': description,
      'geometry': {
        'type': 'Polygon',
        'coordinates': coordinates,
      },
    };

    final response = await ApiClient.post('/parcels', body: body);

    if (response.statusCode == 201) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return Parcel.fromJson(data);
    } else if (response.statusCode == 400) {
      throw Exception('Invalid geometry. Please check coordinates.');
    } else if (response.statusCode == 401) {
      throw Exception('Session expired. Please login again.');
    } else {
      final detail = _extractDetail(response.body);
      throw Exception(detail ?? 'Failed to create parcel (${response.statusCode}).');
    }
  }

  String? _extractDetail(String body) {
    try {
      final data = jsonDecode(body) as Map<String, dynamic>;
      return data['detail'] as String?;
    } catch (_) {
      return null;
    }
  }
}
