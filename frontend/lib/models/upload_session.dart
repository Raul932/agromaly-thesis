/// Models for the GPX cross-device upload session flow.
///
/// These mirror the backend's `app/presentation/schemas/gpx.py` Pydantic models.
library;

// ---------------------------------------------------------------------------
// Session creation response
// ---------------------------------------------------------------------------

/// Returned by POST /api/v1/upload/session.
class UploadSession {
  final String token;
  final String uploadUrl;
  final DateTime expiresAt;

  const UploadSession({
    required this.token,
    required this.uploadUrl,
    required this.expiresAt,
  });

  factory UploadSession.fromJson(Map<String, dynamic> json) {
    return UploadSession(
      token: json['token'] as String,
      uploadUrl: json['upload_url'] as String,
      expiresAt: DateTime.parse(json['expires_at'] as String),
    );
  }
}

// ---------------------------------------------------------------------------
// Per-file GPX parcel preview
// ---------------------------------------------------------------------------

/// Preview extracted from a single GPX file. Not yet saved to the DB.
class GpxParcelPreview {
  final String filename;
  final String name;
  final String? detectedCrop;
  final double? areaHa;
  final String? year;
  final int coordinateCount;
  final double centreLat;
  final double centreLon;

  const GpxParcelPreview({
    required this.filename,
    required this.name,
    this.detectedCrop,
    this.areaHa,
    this.year,
    required this.coordinateCount,
    required this.centreLat,
    required this.centreLon,
  });

  factory GpxParcelPreview.fromJson(Map<String, dynamic> json) {
    return GpxParcelPreview(
      filename: json['filename'] as String,
      name: json['name'] as String,
      detectedCrop: json['detected_crop'] as String?,
      areaHa: (json['area_ha'] as num?)?.toDouble(),
      year: json['year'] as String?,
      coordinateCount: json['coordinate_count'] as int,
      centreLat: (json['centre_lat'] as num).toDouble(),
      centreLon: (json['centre_lon'] as num).toDouble(),
    );
  }
}

// ---------------------------------------------------------------------------
// Session status (polled by the app)
// ---------------------------------------------------------------------------

enum UploadSessionStatus { pending, uploaded, confirmed, expired, unknown }

UploadSessionStatus _parseStatus(String s) {
  switch (s) {
    case 'pending':   return UploadSessionStatus.pending;
    case 'uploaded':  return UploadSessionStatus.uploaded;
    case 'confirmed': return UploadSessionStatus.confirmed;
    case 'expired':   return UploadSessionStatus.expired;
    default:          return UploadSessionStatus.unknown;
  }
}

/// Returned by GET /api/v1/upload/{token}/status.
class UploadStatusResponse {
  final String token;
  final UploadSessionStatus status;
  final List<GpxParcelPreview> parcels;
  final int fileCount;
  final DateTime? expiresAt;

  const UploadStatusResponse({
    required this.token,
    required this.status,
    required this.parcels,
    required this.fileCount,
    this.expiresAt,
  });

  factory UploadStatusResponse.fromJson(Map<String, dynamic> json) {
    final rawParcels = (json['parcels'] as List<dynamic>?) ?? [];
    return UploadStatusResponse(
      token: json['token'] as String,
      status: _parseStatus(json['status'] as String? ?? ''),
      parcels: rawParcels
          .map((p) => GpxParcelPreview.fromJson(p as Map<String, dynamic>))
          .toList(),
      fileCount: json['file_count'] as int? ?? 0,
      expiresAt: json['expires_at'] != null
          ? DateTime.tryParse(json['expires_at'] as String)
          : null,
    );
  }
}

// ---------------------------------------------------------------------------
// Confirm response
// ---------------------------------------------------------------------------

/// Returned by POST /api/v1/upload/{token}/confirm.
class ConfirmUploadResponse {
  final List<String> createdParcelIds;
  final String message;

  const ConfirmUploadResponse({
    required this.createdParcelIds,
    required this.message,
  });

  factory ConfirmUploadResponse.fromJson(Map<String, dynamic> json) {
    final ids = (json['created_parcel_ids'] as List<dynamic>?)
            ?.map((e) => e.toString())
            .toList() ??
        [];
    return ConfirmUploadResponse(
      createdParcelIds: ids,
      message: json['message'] as String? ?? '',
    );
  }
}
