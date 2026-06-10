import 'package:flutter/material.dart';
import '../services/auth_service.dart';

/// Provider managing authentication state.
///
/// Exposes [isLoggedIn], [isLoading], [error] for the UI,
/// and [login] / [logout] for actions.
class AuthProvider extends ChangeNotifier {
  final AuthService _authService = AuthService();

  bool _isLoggedIn = false;
  bool _isLoading = false;
  String? _error;
  String? _userEmail;

  bool get isLoggedIn => _isLoggedIn;
  bool get isLoading => _isLoading;
  String? get error => _error;
  String? get userEmail => _userEmail;

  /// Check stored token on app start.
  Future<void> checkAuthStatus() async {
    _isLoggedIn = await _authService.isLoggedIn();
    if (_isLoggedIn) {
      _userEmail = await _authService.getUserEmail();
    }
    notifyListeners();
  }

  /// Attempt login with email and password.
  Future<bool> login(String email, String password) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _authService.login(email, password);
      _isLoggedIn = true;
      _userEmail = email;
      _isLoading = false;
      notifyListeners();
      return true;
    } on AuthException catch (e) {
      _error = e.message;
      _isLoading = false;
      notifyListeners();
      return false;
    } catch (e) {
      _error = 'Connection error. Is the server running?';
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }

  /// Register a new account.
  ///
  /// Returns [true] on success, [false] on failure (sets [error]).
  Future<bool> signup({
    required String email,
    required String fullName,
    required String password,
    required String passwordConfirm,
  }) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      await _authService.signup(
        email: email,
        fullName: fullName,
        password: password,
        passwordConfirm: passwordConfirm,
      );
      _isLoading = false;
      notifyListeners();
      return true;
    } on AuthException catch (e) {
      _error = e.message;
      _isLoading = false;
      notifyListeners();
      return false;
    } catch (e) {
      _error = 'Connection error. Is the server running?';
      _isLoading = false;
      notifyListeners();
      return false;
    }
  }

  /// Logout and clear token.
  Future<void> logout() async {
    await _authService.logout();
    _isLoggedIn = false;
    _userEmail = null;
    _error = null;
    notifyListeners();
  }

  /// Clear any displayed error.
  void clearError() {
    _error = null;
    notifyListeners();
  }
}
