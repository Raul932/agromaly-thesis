import 'package:latlong2/latlong.dart';

/// Parcel model matching the backend's ParcelResponse schema.
///
/// The [geometryWkt] field contains a WKT MULTIPOLYGON string from PostGIS.
/// Use [polygons] to get parsed LatLng lists for map rendering.
class Parcel {
  final String id;
  final String ownerId;
  final String name;
  final String? description;
  final String geometryWkt;
  final double areaHa;
  final String cropType;
  final String status;
  final double? lastNdvi;
  final String? lastNdviAt;
  final String? lastAnomalyStatus;
  final String createdAt;
  final String updatedAt;

  Parcel({
    required this.id,
    required this.ownerId,
    required this.name,
    this.description,
    required this.geometryWkt,
    required this.areaHa,
    required this.cropType,
    required this.status,
    this.lastNdvi,
    this.lastNdviAt,
    this.lastAnomalyStatus,
    required this.createdAt,
    required this.updatedAt,
  });

  factory Parcel.fromJson(Map<String, dynamic> json) {
    return Parcel(
      id: json['id'] as String,
      ownerId: json['owner_id'] as String,
      name: json['name'] as String,
      description: json['description'] as String?,
      geometryWkt: json['geometry_wkt'] as String,
      areaHa: (json['area_ha'] as num).toDouble(),
      cropType: json['crop_type'] as String? ?? 'UNKNOWN',
      status: json['status'] as String? ?? 'PENDING',
      lastNdvi: json['last_ndvi'] != null
          ? (json['last_ndvi'] as num).toDouble()
          : null,
      lastNdviAt: json['last_ndvi_at'] as String?,
      lastAnomalyStatus: json['last_anomaly_status'] as String?,
      createdAt: json['created_at'] as String,
      updatedAt: json['updated_at'] as String,
    );
  }

  bool get hasAnomaly => lastAnomalyStatus == 'ANOMALY_DETECTED';
  bool get isHealthy => lastAnomalyStatus == 'HEALTHY';
  bool get isInsufficient => lastAnomalyStatus == 'INSUFFICIENT_DATA';

  /// Parse WKT MULTIPOLYGON → list of polygon rings as LatLng lists.
  ///
  /// WKT format: MULTIPOLYGON(((lon lat, lon lat, ...), (hole...)), ((ring2...)))
  /// PostGIS uses lon/lat order (X/Y), so we swap to lat/lon for LatLng.
  List<List<LatLng>> get polygons {
    try {
      return _parseWkt(geometryWkt);
    } catch (_) {
      return [];
    }
  }

  /// Get the centroid of the first polygon for map centering.
  LatLng? get centroid {
    final polys = polygons;
    if (polys.isEmpty || polys.first.isEmpty) return null;
    final ring = polys.first;
    double latSum = 0, lonSum = 0;
    for (final p in ring) {
      latSum += p.latitude;
      lonSum += p.longitude;
    }
    return LatLng(latSum / ring.length, lonSum / ring.length);
  }

  /// Crop type display name with capitalized first letter.
  String get cropTypeDisplay {
    return cropType.replaceAll('_', ' ').split(' ').map((w) {
      if (w.isEmpty) return w;
      return w[0].toUpperCase() + w.substring(1);
    }).join(' ');
  }
}

/// Parse a WKT MULTIPOLYGON or POLYGON string into a list of polygon rings.
///
/// Handles:
///   MULTIPOLYGON(((lon lat, lon lat, ...)))
///   POLYGON((lon lat, lon lat, ...))
List<List<LatLng>> _parseWkt(String wkt) {
  final trimmed = wkt.trim();
  final results = <List<LatLng>>[];

  // Extract coordinate text inside the outermost parentheses
  String inner;
  if (trimmed.toUpperCase().startsWith('MULTIPOLYGON')) {
    // Remove "MULTIPOLYGON(" and trailing ")"
    inner = trimmed.substring(trimmed.indexOf('(') + 1, trimmed.lastIndexOf(')'));
    // inner = "((lon lat, ...), (hole)), ((ring2))"
    // Split by ")),((" to get individual polygons
    final polygonTexts = _splitPolygons(inner);
    for (final polyText in polygonTexts) {
      final ring = _parseRing(polyText);
      if (ring.isNotEmpty) results.add(ring);
    }
  } else if (trimmed.toUpperCase().startsWith('POLYGON')) {
    inner = trimmed.substring(trimmed.indexOf('(') + 1, trimmed.lastIndexOf(')'));
    final ring = _parseRing(inner);
    if (ring.isNotEmpty) results.add(ring);
  }

  return results;
}

/// Split MULTIPOLYGON inner text into individual polygon ring texts.
/// Input like: "((lon lat, ...), (hole)), ((ring2))"
List<String> _splitPolygons(String inner) {
  final results = <String>[];
  int depth = 0;
  int start = 0;

  for (int i = 0; i < inner.length; i++) {
    if (inner[i] == '(') depth++;
    if (inner[i] == ')') depth--;
    if (depth == 0 && i > start) {
      results.add(inner.substring(start, i + 1).trim());
      // Skip comma and whitespace
      start = i + 1;
      while (start < inner.length &&
          (inner[start] == ',' || inner[start] == ' ')) {
        start++;
      }
    }
  }

  return results;
}

/// Parse a single ring text like "(lon lat, lon lat, ...)" → LatLng list.
/// Takes only the outer ring (first parenthesized group), ignoring holes.
List<LatLng> _parseRing(String text) {
  // Remove outer parens
  var cleaned = text.trim();
  while (cleaned.startsWith('(')) {
    cleaned = cleaned.substring(1);
  }
  // Find the first closing paren (end of the outer ring)
  final endIdx = cleaned.indexOf(')');
  if (endIdx > 0) {
    cleaned = cleaned.substring(0, endIdx);
  }

  final coords = <LatLng>[];
  final pairs = cleaned.split(',');
  for (final pair in pairs) {
    final parts = pair.trim().split(RegExp(r'\s+'));
    if (parts.length >= 2) {
      final lon = double.tryParse(parts[0]);
      final lat = double.tryParse(parts[1]);
      if (lon != null && lat != null) {
        coords.add(LatLng(lat, lon)); // WKT is lon/lat, LatLng wants lat/lon
      }
    }
  }
  return coords;
}
