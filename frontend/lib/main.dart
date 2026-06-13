import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'providers/auth_provider.dart';
import 'providers/parcel_provider.dart';
import 'screens/login_screen.dart';
import 'screens/map_screen.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // Force portrait orientation
  SystemChrome.setPreferredOrientations([
    DeviceOrientation.portraitUp,
    DeviceOrientation.portraitDown,
  ]);

  // Edge-to-edge so the app draws behind the status bar and nav bar,
  // and Flutter correctly reports their heights via MediaQuery.
  SystemChrome.setEnabledSystemUIMode(SystemUiMode.edgeToEdge);
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: Colors.transparent,
    systemNavigationBarContrastEnforced: false,
    systemNavigationBarIconBrightness: Brightness.light,
  ));

  runApp(const AgromalyApp());
}

class AgromalyApp extends StatelessWidget {
  const AgromalyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AuthProvider()),
        ChangeNotifierProvider(create: (_) => ParcelProvider()),
      ],
      child: MaterialApp(
        title: 'Agromaly',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          brightness: Brightness.dark,
          scaffoldBackgroundColor: const Color(0xFF0D1B2A),
          primaryColor: const Color(0xFF52B788),
          colorScheme: const ColorScheme.dark(
            primary: Color(0xFF52B788),
            secondary: Color(0xFF2D6A4F),
            surface: Color(0xFF1B4332),
            error: Color(0xFFE76F51),
          ),
          fontFamily: 'Roboto',
          appBarTheme: const AppBarTheme(
            backgroundColor: Color(0xFF0D1B2A),
            elevation: 0,
          ),
          snackBarTheme: SnackBarThemeData(
            backgroundColor: const Color(0xFF1B4332),
            contentTextStyle: const TextStyle(color: Colors.white),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
            behavior: SnackBarBehavior.floating,
          ),
        ),
        home: const _AuthGate(),
      ),
    );
  }
}

/// Checks stored auth token and routes to login or map screen.
class _AuthGate extends StatefulWidget {
  const _AuthGate();

  @override
  State<_AuthGate> createState() => _AuthGateState();
}

class _AuthGateState extends State<_AuthGate> {
  bool _checking = true;

  @override
  void initState() {
    super.initState();
    _checkAuth();
  }

  Future<void> _checkAuth() async {
    await context.read<AuthProvider>().checkAuthStatus();
    if (mounted) {
      setState(() => _checking = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_checking) {
      return const Scaffold(
        backgroundColor: Color(0xFF0D1B2A),
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.eco_rounded, size: 64, color: Color(0xFF52B788)),
              SizedBox(height: 16),
              CircularProgressIndicator(color: Color(0xFF52B788)),
            ],
          ),
        ),
      );
    }

    final isLoggedIn = context.watch<AuthProvider>().isLoggedIn;
    return isLoggedIn ? const MapScreen() : const LoginScreen();
  }
}
