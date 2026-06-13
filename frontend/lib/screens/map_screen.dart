import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';
import '../core/constants.dart';
import '../models/parcel.dart';
import '../providers/auth_provider.dart';
import '../providers/parcel_provider.dart';
import '../services/parcel_service.dart';
import '../widgets/parcel_chat_sheet.dart';
import 'alerts_hub_screen.dart';
import 'analysis_screen.dart';
import 'chat_screen.dart';
import 'import_boundaries_screen.dart';
import 'login_screen.dart';
import 'parcels_panel_screen.dart';

class MapScreen extends StatefulWidget {
  const MapScreen({super.key});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final MapController _mapController = MapController();
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();

  static const _fallbackCenter = LatLng(46.7712, 23.6236);
  static const _defaultZoom = 7.0;

  bool _hasAutocentered = false;
  Parcel? _selectedParcel;

  // NDVI heatmap overlay state
  NdviImageResult? _ndviOverlay;
  bool _loadingNdvi = false;

  // On-map polygon drawing state
  bool _isDrawingMode = false;
  List<LatLng> _draftVertices = [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<ParcelProvider>().loadParcels().then((_) {
        if (!mounted) return;
        _autoCenterOnParcels(context.read<ParcelProvider>().parcels);
      });
    });
  }

  // -------------------------------------------------------------------------
  // Map centering
  // -------------------------------------------------------------------------

  void _autoCenterOnParcels(List<Parcel> parcels) {
    final center = _computeClusterCentroid(parcels);
    if (center != null) {
      _mapController.move(center, 13.0);
    }
    _hasAutocentered = true;
  }

  LatLng? _computeClusterCentroid(List<Parcel> parcels) {
    if (parcels.isEmpty) return null;
    double latSum = 0, lonSum = 0;
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

  void _centerOnParcels(List<Parcel> parcels) {
    final center = _computeClusterCentroid(parcels);
    _mapController.move(
      center ?? _fallbackCenter,
      center != null ? 14.0 : _defaultZoom,
    );
  }

  void _flyTo(LatLng center, double zoom) {
    _mapController.move(center, zoom);
  }

  // -------------------------------------------------------------------------
  // NDVI heatmap fetch
  // -------------------------------------------------------------------------

  Future<void> _fetchNdviOverlay(Parcel parcel) async {
    if (_loadingNdvi) return;
    setState(() {
      _ndviOverlay = null;
      _loadingNdvi = true;
    });
    try {
      final result = await ParcelApiService.fetchNdviImage(parcel.id);
      if (mounted && _selectedParcel?.id == parcel.id) {
        setState(() => _ndviOverlay = result);
      }
    } catch (_) {
      // Silently ignore — map still works without heatmap
    } finally {
      if (mounted) setState(() => _loadingNdvi = false);
    }
  }

  // -------------------------------------------------------------------------
  // Navigation helpers
  // -------------------------------------------------------------------------

  void _openAnalysis(Parcel parcel) {
    setState(() => _selectedParcel = null);
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => AnalysisScreen(parcel: parcel)),
    );
  }

  void _openChat(Parcel parcel) {
    setState(() => _selectedParcel = null);
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => ParcelChatSheet(parcel: parcel),
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
  // Drawing mode helpers
  // -------------------------------------------------------------------------

  void _onDrawingDone() {
    final parcels = context.read<ParcelProvider>().parcels;
    var hasOverlap = false;
    outer:
    for (final vertex in _draftVertices) {
      for (final parcel in parcels) {
        for (final ring in parcel.polygons) {
          if (_isPointInRing(vertex, ring)) {
            hasOverlap = true;
            break outer;
          }
        }
      }
    }

    final nameController = TextEditingController();
    var selectedCropType = 'WHEAT';
    var clipToExisting = hasOverlap;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheetState) => Padding(
          padding: EdgeInsets.only(
              bottom: MediaQuery.of(ctx).viewInsets.bottom +
                  MediaQuery.of(ctx).padding.bottom),
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: const BoxDecoration(
              color: Color(0xFF0D1B2A),
              borderRadius:
                  BorderRadius.vertical(top: Radius.circular(24)),
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Center(
                  child: Container(
                    width: 40,
                    height: 4,
                    decoration: BoxDecoration(
                      color: Colors.white24,
                      borderRadius: BorderRadius.circular(2),
                    ),
                  ),
                ),
                const SizedBox(height: 20),
                const Text(
                  'New Parcel',
                  style: TextStyle(
                      color: Colors.white,
                      fontSize: 18,
                      fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: nameController,
                  style: const TextStyle(color: Colors.white),
                  decoration: InputDecoration(
                    labelText: 'Parcel name *',
                    labelStyle: const TextStyle(color: Colors.white54),
                    enabledBorder: OutlineInputBorder(
                      borderSide:
                          const BorderSide(color: Colors.white24),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderSide: const BorderSide(
                          color: Color(0xFF52B788)),
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: selectedCropType,
                  dropdownColor: const Color(0xFF0D1B2A),
                  style: const TextStyle(color: Colors.white),
                  decoration: InputDecoration(
                    labelText: 'Crop type',
                    labelStyle: const TextStyle(color: Colors.white54),
                    enabledBorder: OutlineInputBorder(
                      borderSide:
                          const BorderSide(color: Colors.white24),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderSide: const BorderSide(
                          color: Color(0xFF52B788)),
                      borderRadius: BorderRadius.circular(12),
                    ),
                  ),
                  items: kCropTypes
                      .map((c) =>
                          DropdownMenuItem(value: c, child: Text(c)))
                      .toList(),
                  onChanged: (v) => setSheetState(
                      () => selectedCropType = v ?? selectedCropType),
                ),
                if (hasOverlap) ...[
                  const SizedBox(height: 8),
                  Container(
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.05),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: CheckboxListTile(
                      title: const Text(
                        'Cut to nearest parcel boundary',
                        style:
                            TextStyle(color: Colors.white, fontSize: 13),
                      ),
                      subtitle: Text(
                        'Overlap detected with an existing parcel',
                        style: TextStyle(
                            color: Colors.orange.shade400, fontSize: 11),
                      ),
                      value: clipToExisting,
                      onChanged: (v) =>
                          setSheetState(() => clipToExisting = v ?? true),
                      activeColor: const Color(0xFF52B788),
                      checkColor: Colors.white,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
                ],
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: () {
                      final name = nameController.text.trim();
                      if (name.isEmpty) return;
                      Navigator.of(ctx).pop();
                      _submitDraftParcel(name, selectedCropType,
                          clipToExisting);
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF52B788),
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                      padding:
                          const EdgeInsets.symmetric(vertical: 14),
                    ),
                    child: const Text('Save Parcel',
                        style:
                            TextStyle(fontWeight: FontWeight.w700)),
                  ),
                ),
                const SizedBox(height: 8),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Future<void> _submitDraftParcel(
      String name, String cropType, bool clipToExisting) async {
    final vertices = List<LatLng>.from(_draftVertices);
    if (vertices.first != vertices.last) {
      vertices.add(vertices.first);
    }

    final coordinates = [
      vertices.map((v) => [v.longitude, v.latitude]).toList(),
    ];

    setState(() {
      _isDrawingMode = false;
      _draftVertices = [];
    });

    try {
      await ParcelApiService().createParcel(
        name: name,
        cropType: cropType,
        coordinates: coordinates,
        clipToExisting: clipToExisting,
      );

      if (!mounted) return;
      final provider = context.read<ParcelProvider>();
      await provider.loadParcels();

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
              'Parcel saved! Satellite sync started in background.'),
          backgroundColor: Color(0xFF52B788),
          duration: Duration(seconds: 3),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('Error saving parcel: $e'),
          backgroundColor: Colors.red,
          duration: const Duration(seconds: 4),
        ),
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
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white60),
            tooltip: 'Refresh parcels',
            onPressed: () {
              _hasAutocentered = false;
              parcelProvider.loadParcels().then((_) {
                if (mounted) _autoCenterOnParcels(parcelProvider.parcels);
              });
            },
          ),
        ],
      ),
      body: Stack(
        children: [
          // ----------------------------------------------------------------
          // flutter_map with Mapbox satellite tiles
          // ----------------------------------------------------------------
          FlutterMap(
            mapController: _mapController,
            options: MapOptions(
              initialCenter: _fallbackCenter,
              initialZoom: _defaultZoom,
              onMapReady: () {
                if (!_hasAutocentered) {
                  _autoCenterOnParcels(parcelProvider.parcels);
                }
              },
              onTap: (_, tapPoint) {
                if (_isDrawingMode) {
                  setState(() => _draftVertices.add(tapPoint));
                  return;
                }
                final tapped = _findParcelAtPoint(
                    tapPoint, parcelProvider.parcels);
                if (tapped != null) {
                  setState(() {
                    _selectedParcel = tapped;
                    _ndviOverlay = null;
                  });
                  _fetchNdviOverlay(tapped);
                } else {
                  setState(() {
                    _selectedParcel = null;
                    _ndviOverlay = null;
                  });
                }
              },
            ),
            children: [
              // 1. Mapbox satellite base tiles
              TileLayer(
                urlTemplate: kMapboxSatelliteUrl,
                userAgentPackageName: 'com.agromaly.agromaly',
              ),

              // 2. NDVI heatmap overlay (shown when a parcel is selected)
              if (_ndviOverlay != null)
                OverlayImageLayer(
                  overlayImages: [
                    OverlayImage(
                      bounds: _ndviOverlay!.bounds,
                      imageProvider: MemoryImage(_ndviOverlay!.imageBytes),
                      opacity: 0.72,
                    ),
                  ],
                ),

              // 3. Parcel polygon outlines
              PolygonLayer(
                polygons: _buildPolygons(parcelProvider.parcels),
              ),

              // 4. Anomaly markers
              MarkerLayer(
                markers: _buildMarkers(parcelProvider.parcels),
              ),

              // 5. Draft polygon preview (active while drawing)
              if (_isDrawingMode && _draftVertices.length >= 2)
                PolylineLayer(
                  polylines: [
                    Polyline(
                      points: [
                        ..._draftVertices,
                        if (_draftVertices.length >= 3) _draftVertices.first,
                      ],
                      color: Colors.white,
                      strokeWidth: 2.5,
                    ),
                  ],
                ),
              if (_isDrawingMode && _draftVertices.length >= 3)
                PolygonLayer(
                  polygons: [
                    Polygon(
                      points: _draftVertices,
                      color: Colors.white.withValues(alpha: 0.15),
                      borderColor: Colors.transparent,
                      borderStrokeWidth: 0,
                    ),
                  ],
                ),
              if (_isDrawingMode && _draftVertices.isNotEmpty)
                MarkerLayer(
                  markers: _draftVertices
                      .asMap()
                      .entries
                      .map(
                        (e) => Marker(
                          point: e.value,
                          width: 16,
                          height: 16,
                          child: Container(
                            decoration: BoxDecoration(
                              color: e.key == 0
                                  ? const Color(0xFF52B788)
                                  : Colors.white,
                              shape: BoxShape.circle,
                              border: Border.all(
                                color: const Color(0xFF0D1B2A),
                                width: 2,
                              ),
                            ),
                          ),
                        ),
                      )
                      .toList(),
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
                    padding: EdgeInsets.symmetric(horizontal: 24, vertical: 12),
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
                        Text('Loading parcels...',
                            style: TextStyle(color: Colors.white70)),
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

          // ----------------------------------------------------------------
          // Drawing mode instruction banner
          // ----------------------------------------------------------------
          if (_isDrawingMode)
            Positioned(
              top: 100,
              left: 16,
              right: 16,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  color: const Color(0xFF0D1B2A).withValues(alpha: 0.93),
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(
                    color: const Color(0xFF52B788).withValues(alpha: 0.45),
                  ),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.touch_app,
                        color: Color(0xFF52B788), size: 18),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        _draftVertices.isEmpty
                            ? 'Tap the map to place parcel vertices'
                            : '${_draftVertices.length} point${_draftVertices.length == 1 ? '' : 's'} placed'
                                ' — continue tapping or press ✓ to finish',
                        style: const TextStyle(
                            color: Colors.white70, fontSize: 13),
                      ),
                    ),
                  ],
                ),
              ),
            ),

          // ----------------------------------------------------------------
          // Parcel count badge
          // ----------------------------------------------------------------
          if (!parcelProvider.isLoading && parcelProvider.parcels.isNotEmpty)
            Positioned(
              bottom: 150,
              left: 16,
              child: Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 14, vertical: 8),
                decoration: BoxDecoration(
                  color: const Color(0xFF0D1B2A).withValues(alpha: 0.9),
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
          // Center-on-parcels FAB
          // ----------------------------------------------------------------
          if (parcelProvider.parcels.isNotEmpty)
            Positioned(
              bottom: 150,
              right: 16,
              child: FloatingActionButton.small(
                heroTag: 'center',
                backgroundColor: const Color(0xFF1B4332),
                onPressed: () => _centerOnParcels(parcelProvider.parcels),
                child: const Icon(Icons.my_location,
                    color: Color(0xFF52B788)),
              ),
            ),

          // ----------------------------------------------------------------
          // Parcel popup card
          // ----------------------------------------------------------------
          if (_selectedParcel != null && !_isDrawingMode)
            Positioned(
              left: 12,
              right: 12,
              bottom: 150,
              child: _buildParcelPopup(_selectedParcel!),
            ),
        ],
      ),
      floatingActionButton: _isDrawingMode
          ? Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                FloatingActionButton.small(
                  heroTag: 'draw_undo',
                  backgroundColor: const Color(0xFF1B2A3A),
                  onPressed: _draftVertices.isEmpty
                      ? null
                      : () => setState(() => _draftVertices.removeLast()),
                  child: const Icon(Icons.undo, color: Colors.white70),
                ),
                const SizedBox(height: 8),
                FloatingActionButton.small(
                  heroTag: 'draw_cancel',
                  backgroundColor: const Color(0xFF1B2A3A),
                  onPressed: () => setState(() {
                    _isDrawingMode = false;
                    _draftVertices = [];
                  }),
                  child: const Icon(Icons.close, color: Color(0xFFE76F51)),
                ),
                const SizedBox(height: 8),
                FloatingActionButton(
                  heroTag: 'draw_done',
                  backgroundColor: _draftVertices.length >= 3
                      ? const Color(0xFF52B788)
                      : Colors.grey.shade700,
                  onPressed:
                      _draftVertices.length >= 3 ? _onDrawingDone : null,
                  child: const Icon(Icons.check, color: Colors.white),
                ),
              ],
            )
          : FloatingActionButton.extended(
              heroTag: 'add_parcel',
              onPressed: () => setState(() {
                _isDrawingMode = true;
                _draftVertices = [];
                _selectedParcel = null;
                _ndviOverlay = null;
              }),
              backgroundColor: const Color(0xFF52B788),
              icon:
                  const Icon(Icons.add_location_alt, color: Colors.white),
              label: const Text(
                'Add Parcel',
                style: TextStyle(
                    color: Colors.white, fontWeight: FontWeight.w600),
              ),
            ),
    );
  }

  // -------------------------------------------------------------------------
  // Parcel popup card
  // -------------------------------------------------------------------------

  Widget _buildParcelPopup(Parcel parcel) {
    final isAnomaly = parcel.status == 'anomaly_detected' ||
        parcel.lastAnomalyStatus == 'ANOMALY_DETECTED';
    final color = _parcelColor(parcel);

    return Material(
      color: Colors.transparent,
      borderRadius: BorderRadius.circular(20),
      child: InkWell(
        onTap: () => _openAnalysis(parcel),
        borderRadius: BorderRadius.circular(20),
        child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: const Color(0xFF0D1B2A).withValues(alpha: 0.97),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withValues(alpha: 0.5), width: 1.5),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withValues(alpha: 0.4),
              blurRadius: 20,
              offset: const Offset(0, 6),
            ),
          ],
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(
                    isAnomaly ? Icons.warning_amber : Icons.eco_rounded,
                    color: color,
                    size: 20,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        parcel.name,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 15,
                          fontWeight: FontWeight.w700,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        parcel.cropTypeDisplay,
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.5),
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                Icon(
                  Icons.chevron_right,
                  color: color.withValues(alpha: 0.6),
                  size: 20,
                ),
                const SizedBox(width: 4),
                IconButton(
                  icon: const Icon(Icons.close,
                      color: Colors.white38, size: 18),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                  onPressed: () => setState(() {
                    _selectedParcel = null;
                    _ndviOverlay = null;
                  }),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                _popupChip(
                  parcel.lastNdvi != null
                      ? 'NDVI ${parcel.lastNdvi!.toStringAsFixed(2)}'
                      : 'No NDVI',
                  color,
                ),
                const SizedBox(width: 8),
                _popupChip(
                  isAnomaly ? '⚠ Anomaly' : 'Healthy',
                  isAnomaly
                      ? const Color(0xFFE76F51)
                      : const Color(0xFF52B788),
                ),
                const SizedBox(width: 8),
                _popupChip(
                  '${parcel.areaHa.toStringAsFixed(1)} ha',
                  Colors.white38,
                ),
                if (_loadingNdvi) ...[
                  const SizedBox(width: 8),
                  const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(
                      strokeWidth: 1.5,
                      color: Color(0xFF4CC9F0),
                    ),
                  ),
                ],
              ],
            ),
            if (_ndviOverlay != null) ...[
              const SizedBox(height: 10),
              _buildNdviLegend(),
            ],
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: () => _openAnalysis(parcel),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF52B788),
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      elevation: 0,
                    ),
                    icon: const Icon(Icons.analytics_outlined, size: 16),
                    label: const Text(
                      'Run Analysis',
                      style: TextStyle(
                          fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: () => _openChat(parcel),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFF4CC9F0),
                      side: BorderSide(
                        color: const Color(0xFF4CC9F0).withValues(alpha: 0.5),
                      ),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                    ),
                    icon: const Icon(Icons.smart_toy_outlined, size: 16),
                    label: const Text(
                      'Ask AI',
                      style: TextStyle(
                          fontSize: 13, fontWeight: FontWeight.w600),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
      ),
    );
  }

  Widget _buildNdviLegend() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(8),
      ),
      child: const Row(
        mainAxisAlignment: MainAxisAlignment.spaceAround,
        children: [
          _LegendDot(color: Color(0xFFD92B2B), label: 'Bare'),
          _LegendDot(color: Color(0xFFE67E22), label: 'Stressed'),
          _LegendDot(color: Color(0xFFD9C02B), label: 'Moderate'),
          _LegendDot(color: Color(0xFF1DB954), label: 'Healthy'),
        ],
      ),
    );
  }

  Widget _popupChip(String label, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.25)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w600,
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
    final initials = email.isNotEmpty ? email[0].toUpperCase() : 'A';
    final parcelsCount = parcelProvider.parcels.length;
    final anomalyCount = parcelProvider.parcels
        .where((p) =>
            p.status == 'anomaly_detected' ||
            p.lastAnomalyStatus == 'ANOMALY_DETECTED')
        .length;

    return Drawer(
      backgroundColor: const Color(0xFF0B1622),
      width: 295,
      child: Column(
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(20, 52, 20, 20),
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [Color(0xFF1B4332), Color(0xFF0B1622)],
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 54,
                      height: 54,
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [Color(0xFF52B788), Color(0xFF40916C)],
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
                        color:
                            const Color(0xFF52B788).withValues(alpha: 0.15),
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
                Row(
                  children: [
                    _statChip('$parcelsCount', 'Parcels',
                        const Color(0xFF52B788)),
                    const SizedBox(width: 8),
                    if (anomalyCount > 0)
                      _statChip('$anomalyCount', 'Alerts',
                          const Color(0xFFE76F51)),
                  ],
                ),
              ],
            ),
          ),
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
                _drawerTile(
                  icon: Icons.map_outlined,
                  label: 'Map Dashboard',
                  subtitle: 'Interactive satellite view',
                  accentColor: const Color(0xFF52B788),
                  onTap: () => Navigator.of(context).pop(),
                ),
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
                        builder: (_) =>
                            ParcelsPanelScreen(onFlyTo: _flyTo),
                      ),
                    );
                  },
                ),
                const Padding(
                  padding: EdgeInsets.fromLTRB(20, 16, 20, 6),
                  child: Text(
                  'INTELIGENȚĂ ARTIFICIALĂ',
                    style: TextStyle(
                      color: Colors.white24,
                      fontSize: 10,
                      letterSpacing: 1.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                _drawerTile(
                  icon: Icons.notifications_active,
                  label: 'Centru Alerte AI',
                  subtitle: anomalyCount > 0
                      ? '$anomalyCount câmp${anomalyCount == 1 ? '' : 'uri'} necesit${anomalyCount == 1 ? 'ă' : 'ă'} atenție'
                      : 'Totul în regulă — fără anomalii',
                  accentColor: anomalyCount > 0
                      ? const Color(0xFFE76F51)
                      : const Color(0xFF40916C),
                  badge: anomalyCount > 0 ? '$anomalyCount' : null,
                  badgeColor: const Color(0xFFE76F51),
                  onTap: () {
                    Navigator.of(context).pop();
                    Navigator.of(context).push(
                      MaterialPageRoute(
                          builder: (_) => const AlertsHubScreen()),
                    );
                  },
                ),
                _drawerTile(
                  icon: Icons.smart_toy,
                  label: 'Agronom AI',
                  subtitle: 'Consultanță agricolă inteligentă',
                  accentColor: const Color(0xFF4CC9F0),
                  onTap: () {
                    Navigator.of(context).pop();
                    Navigator.of(context).push(
                      MaterialPageRoute(
                          builder: (_) => const ChatScreen()),
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
                _drawerTile(
                  icon: Icons.file_upload,
                  label: 'Import Boundaries',
                  subtitle: 'GPX / Shapefile from APIA',
                  accentColor: const Color(0xFFE9C46A),
                  onTap: () async {
                    Navigator.of(context).pop();
                    final result = await Navigator.of(context).push<bool>(
                      MaterialPageRoute(
                          builder: (_) => const ImportBoundariesScreen()),
                    );
                    if (result == true) {
                      _hasAutocentered = false;
                      parcelProvider.loadParcels().then((_) {
                        if (mounted) {
                          _autoCenterOnParcels(parcelProvider.parcels);
                        }
                      });
                    }
                  },
                ),
                const Padding(
                  padding:
                      EdgeInsets.symmetric(horizontal: 20, vertical: 12),
                  child: Divider(color: Colors.white12, height: 1),
                ),
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
            style:
                TextStyle(color: color.withValues(alpha: 0.7), fontSize: 11),
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
            decoration:
                BoxDecoration(borderRadius: BorderRadius.circular(12)),
            child: Row(
              children: [
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
  // Polygon rendering
  // -------------------------------------------------------------------------

  List<Polygon> _buildPolygons(List<Parcel> parcels) {
    final result = <Polygon>[];
    for (final parcel in parcels) {
      final isSelected = _selectedParcel?.id == parcel.id;
      final color = _parcelColor(parcel);
      for (final ring in parcel.polygons) {
        if (ring.length < 3) continue;
        result.add(
          Polygon(
            points: ring,
            color: color.withValues(
              alpha: isSelected && _ndviOverlay != null ? 0.05 : 0.3,
            ),
            borderColor:
                color.withValues(alpha: isSelected ? 1.0 : 0.85),
            borderStrokeWidth: isSelected ? 3.0 : 2.0,
          ),
        );
      }
    }
    return result;
  }

  /// Ray-casting point-in-polygon test. Returns the first parcel whose
  /// polygon contains [point], or null if none match.
  Parcel? _findParcelAtPoint(LatLng point, List<Parcel> parcels) {
    for (final parcel in parcels) {
      for (final ring in parcel.polygons) {
        if (_isPointInRing(point, ring)) return parcel;
      }
    }
    return null;
  }

  bool _isPointInRing(LatLng point, List<LatLng> ring) {
    final n = ring.length;
    bool inside = false;
    double px = point.longitude, py = point.latitude;
    for (int i = 0, j = n - 1; i < n; j = i++) {
      final xi = ring[i].longitude, yi = ring[i].latitude;
      final xj = ring[j].longitude, yj = ring[j].latitude;
      if ((yi > py) != (yj > py) &&
          px < (xj - xi) * (py - yi) / (yj - yi) + xi) {
        inside = !inside;
      }
    }
    return inside;
  }

  Color _parcelColor(Parcel parcel) {
    if (parcel.status == 'anomaly_detected' ||
        parcel.lastAnomalyStatus == 'ANOMALY_DETECTED') {
      return const Color(0xFFFF4444);
    }
    if (parcel.lastNdvi == null) return const Color(0xFF9EA0A5);
    if (parcel.lastNdvi! >= 0.5) return const Color(0xFF52B788);
    if (parcel.lastNdvi! >= 0.3) return const Color(0xFFFFD60A);
    return const Color(0xFFFF8C42);
  }

  // -------------------------------------------------------------------------
  // Anomaly markers
  // -------------------------------------------------------------------------

  List<Marker> _buildMarkers(List<Parcel> parcels) {
    final result = <Marker>[];
    for (final parcel in parcels) {
      if (parcel.status != 'anomaly_detected' &&
          parcel.lastAnomalyStatus != 'ANOMALY_DETECTED') {
        continue;
      }
      final centroid = parcel.centroid;
      if (centroid == null) continue;
      result.add(
        Marker(
          point: centroid,
          width: 36,
          height: 36,
          child: GestureDetector(
            onTap: () {
              setState(() {
                _selectedParcel = parcel;
                _ndviOverlay = null;
              });
              _fetchNdviOverlay(parcel);
            },
            child: Container(
              decoration: BoxDecoration(
                color: const Color(0xFFE76F51),
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFFE76F51).withValues(alpha: 0.5),
                    blurRadius: 10,
                    spreadRadius: 2,
                  ),
                ],
              ),
              child: const Icon(Icons.warning_amber,
                  color: Colors.white, size: 18),
            ),
          ),
        ),
      );
    }
    return result;
  }
}

// -------------------------------------------------------------------------
// Legend dot widget
// -------------------------------------------------------------------------

class _LegendDot extends StatelessWidget {
  final Color color;
  final String label;
  const _LegendDot({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 4),
        Text(label,
            style: const TextStyle(color: Colors.white60, fontSize: 10)),
      ],
    );
  }
}
