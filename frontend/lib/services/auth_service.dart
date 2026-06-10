import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../core/api_client.dart';
import '../core/constants.dart';
import '../models/token.dart';

/// Handles authentication: login, logout, token persistence.
class AuthService {
  static const String _kEmailKey = 'user_email';

  /// Login with email + password via OAuth2 form data.
  ///
  /// The backend expects `application/x-www-form-urlencoded` with
  /// `username` (carrying the email) and `password` fields.
  Future<Token> login(String email, String password) async {
    final response = await ApiClient.postForm(
      '/users/login',
      fields: {
        'username': email,
        'password': password,
      },
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body) as Map<String, dynamic>;
      final token = Token.fromJson(data);
      await _saveToken(token.accessToken);
      await _saveEmail(email);
      return token;
    } else if (response.statusCode == 401) {
      throw AuthException('Invalid email or password.');
    } else if (response.statusCode == 422) {
      throw AuthException('Please check your email and password format.');
    } else {
      throw AuthException(
        'Login failed (${response.statusCode}). Please try again.',
      );
    }
  }

  /// Register a new account via POST /users/signup.
  ///
  /// The backend expects a JSON body with [email], [fullName],
  /// [password], and [passwordConfirm].
  Future<void> signup({
    required String email,
    required String fullName,
    required String password,
    required String passwordConfirm,
  }) async {
    final uri = Uri.parse('$kBaseUrl/users/signup');
    final response = await http.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'email': email,
        'full_name': fullName,
        'password': password,
        'password_confirm': passwordConfirm,
      }),
    );

    if (response.statusCode == 201) {
      return; // success
    } else if (response.statusCode == 400) {
      // Duplicate email — backend returns detail string
      String detail = 'This email is already registered.';
      try {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        if (body['detail'] is String) detail = body['detail'] as String;
      } catch (_) {}
      throw AuthException(detail);
    } else if (response.statusCode == 422) {
      // Pydantic validation error — try to extract first message
      String detail = 'Please check your inputs and try again.';
      try {
        final body = jsonDecode(response.body) as Map<String, dynamic>;
        final errors = body['detail'] as List<dynamic>;
        if (errors.isNotEmpty) {
          final firstError = errors.first as Map<String, dynamic>;
          detail = firstError['msg'] as String? ?? detail;
        }
      } catch (_) {}
      throw AuthException(detail);
    } else {
      throw AuthException(
        'Sign up failed (${response.statusCode}). Please try again.',
      );
    }
  }

  /// Clear the stored token and email.
  Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(kTokenKey);
    await prefs.remove(_kEmailKey);
  }

  /// Check if a token exists in storage.
  Future<bool> isLoggedIn() async {
    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString(kTokenKey);
    return token != null && token.isNotEmpty;
  }

  /// Get the stored user email (may be null if not logged in).
  Future<String?> getUserEmail() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_kEmailKey);
  }

  /// Persist the access token.
  Future<void> _saveToken(String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kTokenKey, token);
  }

  /// Persist the user email for sidebar display.
  Future<void> _saveEmail(String email) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kEmailKey, email);
  }
}

/// Exception thrown on authentication errors.
class AuthException implements Exception {
  final String message;
  AuthException(this.message);

  @override
  String toString() => message;
}
