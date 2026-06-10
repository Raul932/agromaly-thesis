import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';
import '../models/parcel.dart';
import '../providers/auth_provider.dart';
import '../providers/parcel_provider.dart';
import 'add_parcel_screen.dart';
import 'alerts_hub_screen.dart';
import 'analysis_screen.dart';
import 'chat_screen.dart';
import 'import_boundaries_screen.dart';
import 'login_screen.dart';
import 'parcels_panel_screen.dart';

/// Main map dashboard showing the user's parcels as polygons.
///
/// Uses flutter_map with OpenStreetMap tiles (no API key needed).
/// Parcels are rendered by parsing WKT geometry from the backend.
///
/// Features:
///  - Auto-centers map on parcel cluster centroid after data loads.
///  - Global navigation via a premium left-side Drawer.
class MapScreen extends StatefulWidget {
  const MapScreen({super.key});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final MapController _mapController = MapController();
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();

  // Fallback center: Cluj-Napoca, Romania
  static const _fallbackCenter = LatLng(46.7712, 23.6236);
  static const _defaultZoom = 7.0;

  bool _hasAutocentered = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final provider = context.read<ParcelProvider>();
      provider.loadParcels().then((_) {
        if (!mounted) return;
        if (!_hasAutocentered) {
          _autoCenterOnParcels(provider.parcels);
        }
      });
    });
  }

  // -------------------------------------------------------------------------
  // Map centering — computes cluster centroid across ALL parcels
  // -------------------------------------------------------------------------

  /// Computes the mean lat/lon of all parcel centroids and flies the map there.
  /// Falls back to Cluj-Napoca if no parcels have valid geometry.
  void _autoCenterOnParcels(List<Parcel> parcels) {
    final center = _computeClusterCentroid(parcels);
    if (center != null) {
      _mapController.move(center, 13.0);
    }
    _hasAutocentered = true;
  }

  /// Computes the average of all individual parcel centroids.
  LatLng? _computeClusterCentroid(List<Parcel> parcels) {
    if (parcels.isEmpty) return null;

    double latSum = 0;
    double lonSum = 0;
    int count = 0;

    for (final parcel in parcels) {
      final c = parcel.centroid;
      if (c != null) {
        latSum += c.latitude;
        lonSum += c.longitude;
        count++;
      }
    }

    if (count == 0) return null;
    return LatLng(latSum / count, lonSum / count);
  }

  /// Manually center on all parcels (used by the FAB button).
  void _centerOnParcels(List<Parcel> parcels) {
    final center = _computeClusterCentroid(parcels);
    if (center != null) {
      _mapController.move(center, 14.0);
    } else {
      _mapController.move(_fallbackCenter, _defaultZoom);
    }
  }

  /// Fly to a specific coordinate (called from parcels panel).
  void _flyTo(LatLng center, double zoom) {
    _mapController.move(center, zoom);
  }

  // -------------------------------------------------------------------------
  // Navigation helpers
  // -------------------------------------------------------------------------

  void _openAnalysis(Parcel parcel) {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => AnalysisScreen(parcel: parcel)),
    );
  }

  Future<void> _logout() async {
    await context.read<AuthProvider>().logout();
    if (mounted) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (route) => false,
      );
    }
  }

  // -------------------------------------------------------------------------
  // Build
  // -------------------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    final parcelProvider = context.watch<ParcelProvider>();
    final authProvider = context.watch<AuthProvider>();

    return Scaffold(
      key: _scaffoldKey,
      extendBodyBehindAppBar: true,
      drawer: _buildDrawer(context, authProvider, parcelProvider),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D1B2A).withValues(alpha: 0.9),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.menu, color: Colors.white70),
          tooltip: 'Open navigation',
          onPressed: () => _scaffoldKey.currentState?.openDrawer(),
        ),
        title: const Row(
          children: [
            Icon(Icons.eco_rounded, color: Color(0xFF52B788), size: 26),
            SizedBox(width: 10),
            Text(
              'AGROMALY',
              style: TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
                letterSpacing: 3,
                fontSize: 17,
              ),
            ),
          ],
        ),
        actions: [
          // Refresh
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white60),
            tooltip: 'Refresh parcels',
            onPressed: () {
              _hasAutocentered = false;
              parcelProvider.loadParcels().then((_) {
                _autoCenterOnParcels(parcelProvider.parcels);
              });
            },
          ),
        ],
      ),
      body: Stack(
        children: [
          // ----------------------------------------------------------------
          // Map layer
          // ----------------------------------------------------------------
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: _fallbackCenter,
              initialZoom: _defaultZoom,
              maxZoom: 18.0,
              minZoom: 3.0,
              onTap: (tapPosition, point) {
                for (final parcel in parcelProvider.parcels) {
                  for (final ring in parcel.polygons) {
                    if (_isPointInPolygon(point, ring)) {
                      _openAnalysis(parcel);
                      return;
                    }
                  }
                }
              },
            ),
            children: [
              // OpenStreetMap tiles
              TileLayer(
                urlTemplate:
                    'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                userAgentPackageName: 'com.agromaly.app',
                maxZoom: 18,
              ),

              // Parcel polygon overlays
              if (parcelProvider.parcels.isNotEmpty)
                PolygonLayer(
                  polygons: _buildPolygons(parcelProvider.parcels),
                ),
            ],
          ),

          // ----------------------------------------------------------------
          // Loading overlay
          // ----------------------------------------------------------------
          if (parcelProvider.isLoading)
            const Positioned(
              top: 100,
              left: 0,
              right: 0,
              child: Center(
                child: Card(
                  color: Color(0xFF1B4332),
                  child: Padding(
                    padding:
                        EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Color(0xFF52B788),
                          ),
                        ),
                        SizedBox(width: 12),
                        Text(
                          'Loading parcels...',
                          style: TextStyle(color: Colors.white70),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),

          // ----------------------------------------------------------------
          // Error banner
          // ----------------------------------------------------------------
          if (parcelProvider.error != null)
            Positioned(
              top: 100,
              left: 16,
              right: 16,
              child: Material(
                color: Colors.transparent,
                child: Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.red.shade900.withValues(alpha: 0.9),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.warning_amber, color: Colors.white),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          parcelProvider.error!,
                          style: const TextStyle(
                              color: Colors.white, fontSize: 13),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),

          // ----------------------------------------------------------------
          // Parcel count badge
          // ----------------------------------------------------------------
          if (!parcelProvider.isLoading &&
              parcelProvider.parcels.isNotEmpty)
            Positioned(
              bottom: 90,
              left: 16,
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 14, vertical: 8),
                decoration: BoxDecoration(
                  color:
                      const Color(0xFF0D1B2A).withValues(alpha: 0.9),
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(
                    color: const Color(0xFF52B788).withValues(alpha: 0.4),
                  ),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.layers,
                        color: Color(0xFF52B788), size: 18),
                    const SizedBox(width: 6),
                    Text(
                      '${parcelProvider.parcels.length} '
                      'parcel${parcelProvider.parcels.length == 1 ? '' : 's'}',
                      style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                  ],
                ),
              ),
            ),

          // ----------------------------------------------------------------
          // Center-on-parcels mini FAB
          // ----------------------------------------------------------------
          if (parcelProvider.parcels.isNotEmpty)
            Positioned(
              bottom: 90,
              right: 16,
              child: FloatingActionButton.small(
                heroTag: 'center',
                backgroundColor: const Color(0xFF1B4332),
                onPressed: () =>
                    _centerOnParcels(parcelProvider.parcels),
                child: const Icon(Icons.my_location,
                    color: Color(0xFF52B788)),
              ),
            ),
        ],
      ),

      // ----------------------------------------------------------------
      // FAB: Add Parcel
      // ----------------------------------------------------------------
      floatingActionButton: FloatingActionButton.extended(
        heroTag: 'add_parcel',
        onPressed: () async {
          final result = await Navigator.of(context).push<bool>(
            MaterialPageRoute(builder: (_) => const AddParcelScreen()),
          );
          if (result == true) {
            _hasAutocentered = false;
            parcelProvider.loadParcels().then((_) {
              _autoCenterOnParcels(parcelProvider.parcels);
            });
          }
        },
        backgroundColor: const Color(0xFF52B788),
        icon: const Icon(Icons.add_location_alt, color: Colors.white),
        label: const Text(
          'Add Parcel',
          style: TextStyle(
              color: Colors.white, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Drawer
  // -------------------------------------------------------------------------

  Widget _buildDrawer(
    BuildContext context,
    AuthProvider auth,
    ParcelProvider parcelProvider,
  ) {
    final email = auth.userEmail ?? 'farmer@agromaly.com';
    final initials = email.isNotEmpty
        ? email[0].toUpperCase()
        : 'A';
    final parcelsCount = parcelProvider.parcels.length;
    final anomalyCount = parcelProvider.parcels
        .where((p) => p.status == 'anomaly_detected')
        .length;

    return Drawer(
      backgroundColor: const Color(0xFF0B1622),
      width: 295,
      child: Column(
        children: [
          // ----------------------------------------------------------------
          // Drawer header — premium farming profile
          // ----------------------------------------------------------------
          Container(
            padding: const EdgeInsets.fromLTRB(20, 52, 20, 20),
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  Color(0xFF1B4332),
                  Color(0xFF0B1622),
                ],
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Avatar
                Row(
                  children: [
                    Container(
                      width: 54,
                      height: 54,
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [
                            Color(0xFF52B788),
                            Color(0xFF40916C),
                          ],
                        ),
                        borderRadius: BorderRadius.circular(16),
                        boxShadow: [
                          BoxShadow(
                            color: const Color(0xFF52B788)
                                .withValues(alpha: 0.3),
                            blurRadius: 12,
                            offset: const Offset(0, 4),
                          ),
                        ],
                      ),
                      child: Center(
                        child: Text(
                          initials,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 24,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                    ),
                    const Spacer(),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: const Color(0xFF52B788)
                            .withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(
                          color: const Color(0xFF52B788)
                              .withValues(alpha: 0.3),
                        ),
                      ),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.eco,
                              color: Color(0xFF52B788), size: 13),
                          SizedBox(width: 4),
                          Text(
                            'Farmer',
                            style: TextStyle(
                              color: Color(0xFF52B788),
                              fontSize: 11,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),

                // Email
                Text(
                  email,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 12),

                // Stats row
                Row(
                  children: [
                    _statChip(
                      '$parcelsCount',
                      'Parcels',
                      const Color(0xFF52B788),
                    ),
                    const SizedBox(width: 8),
                    if (anomalyCount > 0)
                      _statChip(
                        '$anomalyCount',
                        'Alerts',
                        const Color(0xFFE76F51),
                      ),
                  ],
                ),
              ],
            ),
          ),

          // ----------------------------------------------------------------
          // Navigation items
          // ----------------------------------------------------------------
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(vertical: 8),
              children: [
                const Padding(
                  padding: EdgeInsets.fromLTRB(20, 12, 20, 6),
                  child: Text(
                    'NAVIGATION',
                    style: TextStyle(
                      color: Colors.white24,
                      fontSize: 10,
                      letterSpacing: 1.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),

                // Map Dashboard
                _drawerTile(
                  icon: Icons.map_outlined,
                  label: 'Map Dashboard',
                  subtitle: 'Interactive satellite view',
                  accentColor: const Color(0xFF52B788),
                  onTap: () => Navigator.of(context).pop(),
                ),

                // My Land Parcels
                _drawerTile(
                  icon: Icons.landscape,
                  label: 'My Land Parcels',
                  subtitle: parcelsCount > 0
                      ? '$parcelsCount registered parcel${parcelsCount == 1 ? '' : 's'}'
                      : 'No parcels yet',
                  accentColor: const Color(0xFF74C69D),
                  badge: parcelsCount > 0 ? '$parcelsCount' : null,
                  onTap: () {
                    Navigator.of(context).pop();
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => ParcelsPanelScreen(
                          onFlyTo: _flyTo,
                        ),
                      ),
                    );
                  },
                ),

                const Padding(
                  padding: EdgeInsets.fromLTRB(20, 16, 20, 6),
                  child: Text(
                    'AI INTELLIGENCE',
                    style: TextStyle(
                      color: Colors.white24,
                      fontSize: 10,
                      letterSpacing: 1.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),

                // AI Alerts Hub
                _drawerTile(
                  icon: Icons.notifications_active,
                  label: 'AI Alerts Hub',
                  subtitle: anomalyCount > 0
                      ? '$anomalyCount parcel${anomalyCount == 1 ? '' : 's'} need attention'
                      : 'All clear — no anomalies',
                  accentColor: anomalyCount > 0
                      ? const Color(0xFFE76F51)
                      : const Color(0xFF40916C),
                  badge: anomalyCount > 0 ? '$anomalyCount' : null,
                  badgeColor: const Color(0xFFE76F51),
                  onTap: () {
                    Navigator.of(context).pop();
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const AlertsHubScreen(),
                      ),
                    );
                  },
                ),

                // Global AI Agronomist
                _drawerTile(
                  icon: Icons.smart_toy,
                  label: 'Global AI Agronomist',
                  subtitle: 'RAG-powered crop consulting',
                  accentColor: const Color(0xFF4CC9F0),
                  onTap: () {
                    Navigator.of(context).pop();
                    Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => const ChatScreen(),
                      ),
                    );
                  },
                ),

                const Padding(
                  padding: EdgeInsets.fromLTRB(20, 16, 20, 6),
                  child: Text(
                    'DATA',
                    style: TextStyle(
                      color: Colors.white24,
                      fontSize: 10,
                      letterSpacing: 1.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),

                // Import Boundaries
                _drawerTile(
                  icon: Icons.file_upload,
                  label: 'Import Boundaries',
                  subtitle: 'GPX / Shapefile from APIA',
                  accentColor: const Color(0xFFE9C46A),
                  onTap: () async {
                    Navigator.of(context).pop();
                    final result = await Navigator.of(context).push<bool>(
                      MaterialPageRoute(
                        builder: (_) => const ImportBoundariesScreen(),
                      ),
                    );
                    if (result == true) {
                      _hasAutocentered = false;
                      parcelProvider.loadParcels().then((_) {
                        _autoCenterOnParcels(parcelProvider.parcels);
                      });
                    }
                  },
                ),

                const Padding(
                  padding: EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                  child: Divider(color: Colors.white12, height: 1),
                ),

                // Logout
                _drawerTile(
                  icon: Icons.logout,
                  label: 'Sign Out',
                  subtitle: 'Clear session & return to login',
                  accentColor: const Color(0xFFE76F51),
                  onTap: () {
                    Navigator.of(context).pop();
                    _logout();
                  },
                ),
              ],
            ),
          ),

          // ----------------------------------------------------------------
          // Drawer footer
          // ----------------------------------------------------------------
          Container(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
            child: Row(
              children: [
                const Icon(Icons.eco_rounded,
                    color: Color(0xFF52B788), size: 16),
                const SizedBox(width: 8),
                Text(
                  'Agromaly v1.0 — Bachelor\'s Thesis',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.2),
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _statChip(String value, String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            value,
            style: TextStyle(
              color: color,
              fontSize: 15,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(
              color: color.withValues(alpha: 0.7),
              fontSize: 11,
            ),
          ),
        ],
      ),
    );
  }

  Widget _drawerTile({
    required IconData icon,
    required String label,
    required String subtitle,
    required Color accentColor,
    String? badge,
    Color? badgeColor,
    required VoidCallback onTap,
  }) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
          child: Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                // Icon box
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: accentColor.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(icon, color: accentColor, size: 20),
                ),
                const SizedBox(width: 14),

                // Labels
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        label,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        subtitle,
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.35),
                          fontSize: 11,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),

                // Optional badge
                if (badge != null) ...[
                  const SizedBox(width: 8),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 7, vertical: 2),
                    decoration: BoxDecoration(
                      color: (badgeColor ?? accentColor)
                          .withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      badge,
                      style: TextStyle(
                        color: badgeColor ?? accentColor,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }

  // -------------------------------------------------------------------------
  // Polygon rendering helpers
  // -------------------------------------------------------------------------

  List<Polygon> _buildPolygons(List<Parcel> parcels) {
    final result = <Polygon>[];

    for (final parcel in parcels) {
      final polygonRings = parcel.polygons;
      for (final ring in polygonRings) {
        if (ring.length < 3) continue;
        final fillColor = _parcelColor(parcel);
        result.add(
          Polygon(
            points: ring,
            color: fillColor.withValues(alpha: 0.35),
            borderColor: fillColor,
            borderStrokeWidth: 2.5,
            label: parcel.name,
            labelStyle: const TextStyle(
              color: Colors.white,
              fontSize: 12,
              fontWeight: FontWeight.w600,
            ),
          ),
        );
      }
    }

    return result;
  }

  Color _parcelColor(Parcel parcel) {
    if (parcel.lastNdvi == null) return const Color(0xFF6C757D);
    if (parcel.lastNdvi! >= 0.5) return const Color(0xFF40916C);
    if (parcel.lastNdvi! >= 0.3) return const Color(0xFFE9C46A);
    return const Color(0xFFE76F51);
  }

  // -------------------------------------------------------------------------
  // Point-in-polygon (ray casting)
  // -------------------------------------------------------------------------

  bool _isPointInPolygon(LatLng point, List<LatLng> polygon) {
    bool inside = false;
    int j = polygon.length - 1;
    for (int i = 0; i < polygon.length; i++) {
      if ((polygon[i].latitude > point.latitude) !=
              (polygon[j].latitude > point.latitude) &&
          point.longitude <
              (polygon[j].longitude - polygon[i].longitude) *
                      (point.latitude - polygon[i].latitude) /
                      (polygon[j].latitude - polygon[i].latitude) +
                  polygon[i].longitude) {
        inside = !inside;
      }
      j = i;
    }
    return inside;
  }
}
