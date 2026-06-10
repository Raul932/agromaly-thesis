import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'constants.dart';

/// Centralized HTTP client that auto-injects the JWT Bearer token
/// into every request and provides typed convenience methods.
class ApiClient {
  /// GET request with automatic auth header.
  static Future<http.Response> get(String path) async {
    final headers = await _authHeaders();
    final uri = Uri.parse('$kBaseUrl$path');
    return http.get(uri, headers: headers);
  }

  /// POST request with JSON body and automatic auth header.
  static Future<http.Response> post(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final headers = await _authHeaders();
    headers['Content-Type'] = 'application/json';
    final uri = Uri.parse('$kBaseUrl$path');
    return http.post(
      uri,
      headers: headers,
      body: body != null ? jsonEncode(body) : null,
    );
  }

  /// PATCH request with JSON body and automatic auth header.
  static Future<http.Response> patch(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    final headers = await _authHeaders();
    headers['Content-Type'] = 'application/json';
    final uri = Uri.parse('$kBaseUrl$path');
    return http.patch(
      uri,
      headers: headers,
      body: body != null ? jsonEncode(body) : null,
    );
  }

  /// POST form data (for OAuth2 login).
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

  /// Build authorization headers from stored token.
  static Future<Map<String, String>> _authHeaders() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(kTokenKey);
    if (token != null && token.isNotEmpty) {
      return {'Authorization': 'Bearer $token'};
    }
    return {};
  }
}
