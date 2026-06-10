import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';
import '../models/parcel.dart';
import '../providers/parcel_provider.dart';

/// Slide-in panel showing all parcels as cards.
/// Tapping a card triggers [onFlyTo] to animate the map camera.
class ParcelsPanelScreen extends StatelessWidget {
  /// Called when the user taps a parcel card — fly the map to its centroid.
  final void Function(LatLng center, double zoom) onFlyTo;

  const ParcelsPanelScreen({super.key, required this.onFlyTo});

  Color _statusColor(Parcel p) {
    if (p.lastNdvi == null) return const Color(0xFF6C757D);
    if (p.lastNdvi! >= 0.5) return const Color(0xFF40916C);
    if (p.lastNdvi! >= 0.3) return const Color(0xFFE9C46A);
    return const Color(0xFFE76F51);
  }

  IconData _cropIcon(String cropType) {
    switch (cropType) {
      case 'wheat':
      case 'barley':
        return Icons.grass;
      case 'corn':
        return Icons.energy_savings_leaf;
      case 'vineyard':
        return Icons.local_florist;
      case 'potato':
      case 'sugar_beet':
        return Icons.agriculture;
      default:
        return Icons.eco;
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ParcelProvider>();
    final parcels = provider.parcels;

    return Scaffold(
      backgroundColor: const Color(0xFF0D1B2A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D1B2A),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.white70),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: const Row(
          children: [
            Icon(Icons.landscape, color: Color(0xFF52B788), size: 22),
            SizedBox(width: 10),
            Text(
              'My Land Parcels',
              style: TextStyle(
                color: Colors.white,
                fontSize: 17,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white54),
            onPressed: () => provider.loadParcels(),
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: _buildBody(context, provider, parcels),
    );
  }

  Widget _buildBody(
      BuildContext context, ParcelProvider provider, List<Parcel> parcels) {
    if (provider.isLoading) {
      return const Center(
        child: CircularProgressIndicator(color: Color(0xFF52B788)),
      );
    }

    if (provider.error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.cloud_off, color: Colors.white38, size: 52),
              const SizedBox(height: 16),
              Text(
                provider.error!,
                textAlign: TextAlign.center,
                style: const TextStyle(color: Colors.white54, fontSize: 14),
              ),
              const SizedBox(height: 24),
              OutlinedButton(
                onPressed: provider.loadParcels,
                style: OutlinedButton.styleFrom(
                  side: const BorderSide(color: Color(0xFF52B788)),
                ),
                child: const Text(
                  'Retry',
                  style: TextStyle(color: Color(0xFF52B788)),
                ),
              ),
            ],
          ),
        ),
      );
    }

    if (parcels.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.map_outlined, color: Colors.white24, size: 64),
            const SizedBox(height: 16),
            const Text(
              'No parcels registered yet.',
              style: TextStyle(color: Colors.white38, fontSize: 16),
            ),
            const SizedBox(height: 8),
            Text(
              'Use the "Add Parcel" button on the map to get started.',
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.25),
                fontSize: 13,
              ),
            ),
          ],
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      itemCount: parcels.length,
      separatorBuilder: (_, __) => const SizedBox(height: 10),
      itemBuilder: (context, index) => _parcelCard(context, parcels[index]),
    );
  }

  Widget _parcelCard(BuildContext context, Parcel parcel) {
    final color = _statusColor(parcel);
    final centroid = parcel.centroid;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: centroid == null
            ? null
            : () {
                // Close drawer + this screen and fly to parcel
                Navigator.of(context).pop(); // close parcels panel
                onFlyTo(centroid, 15.0);
              },
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.04),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: color.withValues(alpha: 0.3),
              width: 1.2,
            ),
          ),
          child: Row(
            children: [
              // Crop icon circle
              Container(
                width: 48,
                height: 48,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.15),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(_cropIcon(parcel.cropType), color: color, size: 24),
              ),
              const SizedBox(width: 14),

              // Parcel info
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      parcel.name,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 4),
                    Row(
                      children: [
                        Text(
                          parcel.cropTypeDisplay,
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.5),
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Container(
                          width: 4,
                          height: 4,
                          decoration: const BoxDecoration(
                            color: Colors.white24,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 8),
                        Text(
                          '${parcel.areaHa.toStringAsFixed(2)} ha',
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.5),
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    // NDVI chip
                    _ndviChip(parcel, color),
                  ],
                ),
              ),

              // Navigate arrow
              if (centroid != null) ...[
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Icon(Icons.my_location, color: color, size: 18),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _ndviChip(Parcel parcel, Color color) {
    final label = parcel.lastNdvi != null
        ? 'NDVI ${parcel.lastNdvi!.toStringAsFixed(2)}'
        : 'No NDVI data';
    final statusLabel = _statusLabel(parcel.status);
    return Row(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
            color: color.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
        const SizedBox(width: 6),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.06),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(
            statusLabel,
            style: const TextStyle(
              color: Colors.white38,
              fontSize: 11,
            ),
          ),
        ),
      ],
    );
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'active':
        return 'Active';
      case 'pending':
        return 'Pending';
      case 'anomaly_detected':
        return '⚠ Anomaly';
      default:
        return status;
    }
  }
}
