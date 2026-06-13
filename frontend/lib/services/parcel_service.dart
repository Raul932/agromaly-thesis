import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../core/api_client.dart';
import '../models/parcel.dart';

/// Result of a NDVI spatial image fetch — contains the PNG bytes and its
/// geographic bounding box for rendering as a map overlay.
class NdviImageResult {
  final Uint8List imageBytes;
  final LatLngBounds bounds;
  const NdviImageResult({required this.imageBytes, required this.bounds});
}

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
  /// [areaHa] is optional — when omitted the backend calculates it automatically.
  /// [clipToExisting] removes overlap with the user's existing parcels server-side.
  Future<Parcel> createParcel({
    required String name,
    required String cropType,
    double? areaHa,
    String? description,
    required List<List<List<double>>> coordinates,
    bool clipToExisting = false,
  }) async {
    final body = {
      'name': name,
      'crop_type': cropType,
      if (areaHa != null) 'area_ha': areaHa,
      if (description != null && description.isNotEmpty)
        'description': description,
      'geometry': {
        'type': 'Polygon',
        'coordinates': coordinates,
      },
      if (clipToExisting) 'clip_to_existing': true,
    };

    final response = await ApiClient.post('/parcels', body: body);

    if (response.statusCode == 201) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return Parcel.fromJson(data);
    } else if (response.statusCode == 400) {
      throw Exception('Invalid geometry. Please check coordinates.');
    } else if (response.statusCode == 401) {
      throw Exception('Session expired. Please login again.');
    } else if (response.statusCode == 409) {
      final detail = _extractDetail(response.body);
      throw Exception(detail ?? 'A parcel with this name already exists.');
    } else {
      final detail = _extractDetail(response.body);
      throw Exception(detail ?? 'Failed to create parcel (${response.statusCode}).');
    }
  }

  /// Queue NDVI + weather satellite sync for a parcel.
  ///
  /// Returns the [message] from the server. If [recentlySynced] is true in
  /// the response, the sync was skipped because data is already fresh.
  Future<({String message, bool recentlySynced, int recordsSaved})> syncParcel(
      String parcelId) async {
    final response = await ApiClient.post('/parcels/$parcelId/sync', body: {});
    if (response.statusCode == 200 || response.statusCode == 202) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return (
        message: data['message'] as String? ?? 'Done.',
        recentlySynced: data['recently_synced'] as bool? ?? false,
        recordsSaved: data['records_saved'] as int? ?? 0,
      );
    }
    if (response.statusCode == 403) {
      throw Exception('You do not have permission to sync this parcel.');
    }
    if (response.statusCode == 404) {
      throw Exception('Parcel not found.');
    }
    final detail = _extractDetail(response.body);
    throw Exception(detail ?? 'Sync failed (${response.statusCode}).');
  }

  /// Sync NDVI + weather for all parcels owned by the current user.
  Future<({String message, int synced, int skipped, int recordsSaved})>
      syncAllParcels() async {
    final response =
        await ApiClient.post('/parcels/sync-all', body: {});
    if (response.statusCode == 200 || response.statusCode == 202) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return (
        message: data['message'] as String? ?? 'Done.',
        synced: data['synced'] as int? ?? 0,
        skipped: data['skipped'] as int? ?? 0,
        recordsSaved: data['records_saved'] as int? ?? 0,
      );
    }
    if (response.statusCode == 401) {
      throw Exception('Session expired. Please login again.');
    }
    final detail = _extractDetail(response.body);
    throw Exception(detail ?? 'Sync all failed (${response.statusCode}).');
  }

  /// Update parcel metadata (name, description, crop_type).
  ///
  /// Only provided (non-null) fields are sent to the server.
  Future<Parcel> updateParcel(
    String parcelId, {
    String? name,
    String? description,
    String? cropType,
  }) async {
    final body = <String, dynamic>{};
    if (name != null) body['name'] = name;
    if (description != null) body['description'] = description;
    if (cropType != null) body['crop_type'] = cropType;

    final response = await ApiClient.patch('/parcels/$parcelId', body: body);

    if (response.statusCode == 200) {
      return Parcel.fromJson(jsonDecode(response.body) as Map<String, dynamic>);
    }
    if (response.statusCode == 403) {
      throw Exception('You do not have permission to update this parcel.');
    }
    if (response.statusCode == 404) {
      throw Exception('Parcel not found.');
    }
    final detail = _extractDetail(response.body);
    throw Exception(detail ?? 'Failed to update parcel (${response.statusCode}).');
  }

  /// Delete a parcel by ID. Throws on non-204 responses.
  Future<void> deleteParcel(String parcelId) async {
    final response = await ApiClient.delete('/parcels/$parcelId');
    if (response.statusCode == 204) return;
    if (response.statusCode == 403) {
      throw Exception('You do not have permission to delete this parcel.');
    }
    if (response.statusCode == 404) {
      throw Exception('Parcel not found.');
    }
    final detail = _extractDetail(response.body);
    throw Exception(detail ?? 'Failed to delete parcel (${response.statusCode}).');
  }

  String? _extractDetail(String body) {
    try {
      final data = jsonDecode(body) as Map<String, dynamic>;
      return data['detail'] as String?;
    } catch (_) {
      return null;
    }
  }

  /// Fetch the NDVI spatial heatmap image for a parcel.
  ///
  /// Returns a [NdviImageResult] with the PNG bytes and geographic bounds,
  /// or throws if the request fails.
  static Future<NdviImageResult> fetchNdviImage(String parcelId) async {
    final response =
        await ApiClient.get('/parcels/$parcelId/ndvi-image');
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final base64Str = data['image_base64'] as String;
      final boundsMap = data['bounds'] as Map<String, dynamic>;

      final imageBytes = base64Decode(base64Str);
      final bounds = LatLngBounds(
        LatLng(
          (boundsMap['south'] as num).toDouble(),
          (boundsMap['west'] as num).toDouble(),
        ),
        LatLng(
          (boundsMap['north'] as num).toDouble(),
          (boundsMap['east'] as num).toDouble(),
        ),
      );
      return NdviImageResult(imageBytes: imageBytes, bounds: bounds);
    }
    throw Exception('NDVI image fetch failed (${response.statusCode}).');
  }
}
