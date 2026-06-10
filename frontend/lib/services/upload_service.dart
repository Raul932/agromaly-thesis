import 'dart:convert';
import '../core/api_client.dart';
import '../models/upload_session.dart';

/// Service for the cross-device GPX upload session flow.
///
/// Wraps all endpoints under /api/v1/upload/.
/// Uses [ApiClient] which auto-injects the JWT Bearer token.
class UploadService {
  // -------------------------------------------------------------------------
  // POST /api/v1/upload/session
  // -------------------------------------------------------------------------

  /// Create a new 15-minute upload session.
  ///
  /// Returns an [UploadSession] containing the token and the URL to display
  /// as a QR code on the mobile screen.
  ///
  /// Throws [UploadException] on failure.
  Future<UploadSession> createSession() async {
    final response = await ApiClient.post('/upload/session');

    if (response.statusCode == 201) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return UploadSession.fromJson(data);
    }
    final detail = _extractDetail(response.body);
    throw UploadException('Failed to create upload session: $detail');
  }

  // -------------------------------------------------------------------------
  // GET /api/v1/upload/{token}/status
  // -------------------------------------------------------------------------

  /// Poll the current status of an upload session.
  ///
  /// Called every ~3 seconds by the QR screen while waiting for files.
  /// Returns [UploadStatusResponse] with status and (when uploaded) previews.
  Future<UploadStatusResponse> pollStatus(String token) async {
    final response = await ApiClient.get('/upload/$token/status');

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return UploadStatusResponse.fromJson(data);
    } else if (response.statusCode == 404) {
      // Session has expired — surface as expired status
      return UploadStatusResponse(
        token: token,
        status: UploadSessionStatus.expired,
        parcels: const [],
        fileCount: 0,
      );
    }
    final detail = _extractDetail(response.body);
    throw UploadException('Status poll failed: $detail');
  }

  // -------------------------------------------------------------------------
  // POST /api/v1/upload/{token}/confirm
  // -------------------------------------------------------------------------

  /// Confirm previewed parcels and persist them to the database.
  ///
  /// Returns [ConfirmUploadResponse] with the IDs of the created parcels.
  Future<ConfirmUploadResponse> confirmUpload(String token) async {
    final response = await ApiClient.post('/upload/$token/confirm');

    if (response.statusCode == 201) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      return ConfirmUploadResponse.fromJson(data);
    }
    final detail = _extractDetail(response.body);
    throw UploadException('Confirm failed: $detail');
  }

  // -------------------------------------------------------------------------
  // Private helpers
  // -------------------------------------------------------------------------

  String _extractDetail(String body) {
    try {
      final parsed = jsonDecode(body) as Map<String, dynamic>;
      return parsed['detail']?.toString() ?? body;
    } catch (_) {
      return body;
    }
  }
}

/// Exception thrown when any upload service call fails.
class UploadException implements Exception {
  final String message;
  const UploadException(this.message);

  @override
  String toString() => message;
}
