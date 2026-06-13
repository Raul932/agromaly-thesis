import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'constants.dart';

/// Centralized HTTP client that auto-injects the JWT Bearer token
/// into every request and provides typed convenience methods.
///
/// On any 401 response, the client attempts a token refresh once using
/// the stored refresh token, then retries the original request.
class ApiClient {
  /// GET request with automatic auth header and 401 retry.
  static Future<http.Response> get(String path) async {
    final uri = Uri.parse('$kBaseUrl$path');
    var response = await http.get(uri, headers: await _authHeaders());
    if (response.statusCode == 401) {
      if (await _tryRefreshToken()) {
        response = await http.get(uri, headers: await _authHeaders());
      }
    }
    return response;
  }

  /// POST request with JSON body, automatic auth header and 401 retry.
  static Future<http.Response> post(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse('$kBaseUrl$path');
    final encoded = body != null ? jsonEncode(body) : null;
    var response = await http.post(
      uri,
      headers: {...await _authHeaders(), 'Content-Type': 'application/json'},
      body: encoded,
    );
    if (response.statusCode == 401) {
      if (await _tryRefreshToken()) {
        response = await http.post(
          uri,
          headers: {...await _authHeaders(), 'Content-Type': 'application/json'},
          body: encoded,
        );
      }
    }
    return response;
  }

  /// PATCH request with JSON body, automatic auth header and 401 retry.
  static Future<http.Response> patch(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final uri = Uri.parse('$kBaseUrl$path');
    final encoded = body != null ? jsonEncode(body) : null;
    var response = await http.patch(
      uri,
      headers: {...await _authHeaders(), 'Content-Type': 'application/json'},
      body: encoded,
    );
    if (response.statusCode == 401) {
      if (await _tryRefreshToken()) {
        response = await http.patch(
          uri,
          headers: {...await _authHeaders(), 'Content-Type': 'application/json'},
          body: encoded,
        );
      }
    }
    return response;
  }

  /// DELETE request with automatic auth header and 401 retry.
  static Future<http.Response> delete(String path) async {
    final uri = Uri.parse('$kBaseUrl$path');
    var response = await http.delete(uri, headers: await _authHeaders());
    if (response.statusCode == 401) {
      if (await _tryRefreshToken()) {
        response = await http.delete(uri, headers: await _authHeaders());
      }
    }
    return response;
  }

  /// POST form data (for OAuth2 login) — no auth header needed.
  static Future<http.Response> postForm(
    String path, {
    required Map<String, String> fields,
  }) async {
    final uri = Uri.parse('$kBaseUrl$path');
    return http.post(
      uri,
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: fields,
    );
  }

  /// Build authorization headers from the stored access token.
  static Future<Map<String, String>> _authHeaders() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(kTokenKey);
    if (token != null && token.isNotEmpty) {
      return {'Authorization': 'Bearer $token'};
    }
    return {};
  }

  /// Attempt to refresh the access token using the stored refresh token.
  /// Returns true if a new access token was obtained and saved.
  static Future<bool> _tryRefreshToken() async {
    final prefs = await SharedPreferences.getInstance();
    final refreshToken = prefs.getString(kRefreshTokenKey);
    if (refreshToken == null || refreshToken.isEmpty) return false;

    try {
      final uri = Uri.parse('$kBaseUrl/users/refresh');
      final response = await http.post(
        uri,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': refreshToken}),
      );
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        await prefs.setString(kTokenKey, data['access_token'] as String);
        final newRefresh = data['refresh_token'] as String?;
        if (newRefresh != null) {
          await prefs.setString(kRefreshTokenKey, newRefresh);
        }
        return true;
      }
    } catch (_) {}
    return false;
  }
}
