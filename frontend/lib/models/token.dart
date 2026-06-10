/// JWT token response from POST /api/v1/users/login.
class Token {
  final String accessToken;
  final String refreshToken;
  final String tokenType;
  final int expiresIn;

  Token({
    required this.accessToken,
    required this.refreshToken,
    required this.tokenType,
    required this.expiresIn,
  });

  factory Token.fromJson(Map<String, dynamic> json) {
    return Token(
      accessToken: json['access_token'] as String,
      refreshToken: json['refresh_token'] as String,
      tokenType: json['token_type'] as String? ?? 'bearer',
      expiresIn: json['expires_in'] as int? ?? 1800,
    );
  }
}
