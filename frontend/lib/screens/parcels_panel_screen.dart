import 'package:flutter/material.dart';
import 'package:latlong2/latlong.dart';
import 'package:provider/provider.dart';
import '../core/constants.dart';
import '../models/parcel.dart';
import '../providers/parcel_provider.dart';
import '../services/parcel_service.dart';
import 'analysis_screen.dart';

class ParcelsPanelScreen extends StatefulWidget {
  final void Function(LatLng center, double zoom) onFlyTo;

  const ParcelsPanelScreen({super.key, required this.onFlyTo});

  @override
  State<ParcelsPanelScreen> createState() => _ParcelsPanelScreenState();
}

class _ParcelsPanelScreenState extends State<ParcelsPanelScreen> {
  String? _deletingId;
  String? _updatingId;
  bool _isSyncingAll = false;
  final ParcelApiService _parcelService = ParcelApiService();

  // Filter state
  String _healthFilter = 'ALL';
  String _cropFilter = 'ALL';

  // ── Health colours driven by anomaly status ─────────────────────────
  Color _statusColor(Parcel p) {
    switch (p.lastAnomalyStatus) {
      case 'ANOMALY_DETECTED':
        return const Color(0xFFE76F51);
      case 'HEALTHY':
        return const Color(0xFF40916C);
      case 'INSUFFICIENT_DATA':
        return const Color(0xFFE9C46A);
      default:
        // No analysis yet — fall back to raw NDVI thresholds
        if (p.lastNdvi == null) return const Color(0xFF6C757D);
        if (p.lastNdvi! >= 0.5) return const Color(0xFF40916C);
        if (p.lastNdvi! >= 0.3) return const Color(0xFFE9C46A);
        return const Color(0xFFE76F51);
    }
  }

  String _healthLabel(Parcel p) {
    switch (p.lastAnomalyStatus) {
      case 'ANOMALY_DETECTED':
        return '⚠ Needs Attention';
      case 'HEALTHY':
        return '✓ Healthy';
      case 'INSUFFICIENT_DATA':
        return 'Checking...';
      default:
        return p.lastNdvi != null ? 'Not Analysed' : 'No Data Yet';
    }
  }

  IconData _cropIcon(String cropType) {
    switch (cropType) {
      case 'WHEAT':
      case 'BARLEY':
        return Icons.grass;
      case 'CORN':
        return Icons.energy_savings_leaf;
      case 'VINEYARD':
        return Icons.local_florist;
      case 'POTATO':
      case 'SUGAR_BEET':
        return Icons.agriculture;
      case 'MEADOW':
        return Icons.nature;
      default:
        return Icons.eco;
    }
  }

  // ── Filtering ────────────────────────────────────────────────────────
  List<Parcel> _applyFilters(List<Parcel> all) {
    return all.where((p) {
      final healthOk = _healthFilter == 'ALL' ||
          (_healthFilter == 'NO_DATA' && p.lastAnomalyStatus == null) ||
          p.lastAnomalyStatus == _healthFilter;
      final cropOk = _cropFilter == 'ALL' || p.cropType == _cropFilter;
      return healthOk && cropOk;
    }).toList();
  }

  List<String> _presentCropTypes(List<Parcel> all) {
    final seen = <String>{};
    for (final p in all) {
      seen.add(p.cropType);
    }
    return seen.toList()..sort();
  }

  // ── Sync all ─────────────────────────────────────────────────────────
  Future<void> _syncAllParcels() async {
    if (_isSyncingAll) return;
    setState(() => _isSyncingAll = true);
    try {
      final result = await _parcelService.syncAllParcels();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(result.message),
          backgroundColor: const Color(0xFF2D6A4F),
          duration: const Duration(seconds: 5),
        ),
      );
      context.read<ParcelProvider>().loadParcels();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', '')),
          backgroundColor: Colors.redAccent,
        ),
      );
    } finally {
      if (mounted) setState(() => _isSyncingAll = false);
    }
  }

  // ── Edit dialog ──────────────────────────────────────────────────────
  Future<void> _showEditDialog(BuildContext context, Parcel parcel) async {
    final nameCtrl = TextEditingController(text: parcel.name);
    final descCtrl = TextEditingController(text: parcel.description ?? '');
    String selectedCrop = parcel.cropType;
    final formKey = GlobalKey<FormState>();

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setDialogState) => AlertDialog(
          backgroundColor: const Color(0xFF132233),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          title: const Text('Edit Field',
              style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
          content: Form(
            key: formKey,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  TextFormField(
                    controller: nameCtrl,
                    style: const TextStyle(color: Colors.white),
                    decoration: _inputDecoration('Field Name'),
                    validator: (v) {
                      if (v == null || v.trim().isEmpty) return 'Name is required';
                      if (v.trim().length > 255) return 'Name too long';
                      return null;
                    },
                  ),
                  const SizedBox(height: 12),
                  TextFormField(
                    controller: descCtrl,
                    maxLines: 2,
                    style: const TextStyle(color: Colors.white),
                    decoration: _inputDecoration('Notes (optional)'),
                  ),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: selectedCrop,
                    dropdownColor: const Color(0xFF1B4332),
                    style: const TextStyle(color: Colors.white),
                    icon: const Icon(Icons.expand_more, color: Colors.white54),
                    decoration: _inputDecoration('Crop Type'),
                    items: kCropTypes
                        .map((t) => DropdownMenuItem(
                              value: t,
                              child: Text(t.replaceAll('_', ' ').toUpperCase()),
                            ))
                        .toList(),
                    onChanged: (v) {
                      if (v != null) setDialogState(() => selectedCrop = v);
                    },
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(false),
              child: const Text('Cancel', style: TextStyle(color: Colors.white54)),
            ),
            TextButton(
              onPressed: () {
                if (formKey.currentState!.validate()) Navigator.of(ctx).pop(true);
              },
              style: TextButton.styleFrom(foregroundColor: const Color(0xFF52B788)),
              child: const Text('Save', style: TextStyle(fontWeight: FontWeight.w700)),
            ),
          ],
        ),
      ),
    );

    if (confirmed != true || !context.mounted) return;

    setState(() => _updatingId = parcel.id);
    final provider = context.read<ParcelProvider>();
    final ok = await provider.updateParcel(
      parcel.id,
      name: nameCtrl.text.trim(),
      description: descCtrl.text.trim().isEmpty ? null : descCtrl.text.trim(),
      cropType: selectedCrop,
    );
    if (mounted) setState(() => _updatingId = null);

    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(provider.error ?? 'Failed to update field.'),
          backgroundColor: const Color(0xFFE76F51),
        ),
      );
    }
  }

  Future<void> _confirmDelete(BuildContext context, Parcel parcel) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF132233),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Delete Field',
            style: TextStyle(color: Colors.white, fontWeight: FontWeight.w700)),
        content: RichText(
          text: TextSpan(
            style: const TextStyle(color: Colors.white70, fontSize: 14, height: 1.5),
            children: [
              const TextSpan(text: 'Are you sure you want to delete '),
              TextSpan(
                text: parcel.name,
                style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600),
              ),
              const TextSpan(
                text: '?\n\nThis will permanently remove the field and all its satellite data and alerts.',
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel', style: TextStyle(color: Colors.white54)),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: TextButton.styleFrom(foregroundColor: const Color(0xFFE76F51)),
            child: const Text('Delete', style: TextStyle(fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );

    if (confirmed != true || !context.mounted) return;

    setState(() => _deletingId = parcel.id);
    final provider = context.read<ParcelProvider>();
    final ok = await provider.deleteParcel(parcel.id);
    if (mounted) setState(() => _deletingId = null);

    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(provider.error ?? 'Failed to delete field.'),
          backgroundColor: const Color(0xFFE76F51),
        ),
      );
    }
  }

  // ── Build ─────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final provider = context.watch<ParcelProvider>();
    final parcels = provider.parcels;
    final filtered = _applyFilters(parcels);
    final cropTypes = _presentCropTypes(parcels);

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
              'My Fields',
              style: TextStyle(
                  color: Colors.white, fontSize: 17, fontWeight: FontWeight.w600),
            ),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Update satellite data for all fields',
            icon: _isSyncingAll
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                        color: Color(0xFF52B788), strokeWidth: 2.5),
                  )
                : const Icon(Icons.satellite_alt, color: Colors.white54),
            onPressed: _isSyncingAll ? null : _syncAllParcels,
          ),
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white54),
            onPressed: () => provider.loadParcels(),
            tooltip: 'Refresh',
          ),
        ],
      ),
      body: Column(
        children: [
          // ── Filter chips ─────────────────────────────────────────────
          if (parcels.isNotEmpty) ...[
            _buildHealthFilterRow(parcels),
            if (cropTypes.length > 1) _buildCropFilterRow(cropTypes),
            const Divider(height: 1, color: Colors.white12),
          ],
          Expanded(child: _buildBody(context, provider, filtered, parcels)),
        ],
      ),
    );
  }

  Widget _buildHealthFilterRow(List<Parcel> all) {
    final anomalyCount =
        all.where((p) => p.lastAnomalyStatus == 'ANOMALY_DETECTED').length;
    final healthyCount =
        all.where((p) => p.lastAnomalyStatus == 'HEALTHY').length;
    final noDataCount =
        all.where((p) => p.lastAnomalyStatus == null).length;

    final chips = [
      ('ALL', 'All (${all.length})', null),
      ('ANOMALY_DETECTED', '⚠ Attention ($anomalyCount)', const Color(0xFFE76F51)),
      ('HEALTHY', '✓ Healthy ($healthyCount)', const Color(0xFF40916C)),
      ('NO_DATA', 'No Data ($noDataCount)', const Color(0xFF6C757D)),
    ];

    return SizedBox(
      height: 44,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        itemCount: chips.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final (key, label, color) = chips[i];
          final isSelected = _healthFilter == key;
          final chipColor = color ?? const Color(0xFF52B788);
          return GestureDetector(
            onTap: () => setState(() => _healthFilter = key),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
              decoration: BoxDecoration(
                color: isSelected
                    ? chipColor.withValues(alpha: 0.2)
                    : Colors.white.withValues(alpha: 0.05),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(
                  color: isSelected
                      ? chipColor
                      : Colors.white.withValues(alpha: 0.15),
                  width: isSelected ? 1.5 : 1,
                ),
              ),
              child: Text(
                label,
                style: TextStyle(
                  color: isSelected ? chipColor : Colors.white54,
                  fontSize: 12,
                  fontWeight:
                      isSelected ? FontWeight.w700 : FontWeight.w400,
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildCropFilterRow(List<String> cropTypes) {
    final all = ['ALL', ...cropTypes];
    return SizedBox(
      height: 38,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        itemCount: all.length,
        separatorBuilder: (_, __) => const SizedBox(width: 6),
        itemBuilder: (_, i) {
          final key = all[i];
          final label =
              key == 'ALL' ? 'All Crops' : key.replaceAll('_', ' ');
          final isSelected = _cropFilter == key;
          return GestureDetector(
            onTap: () => setState(() => _cropFilter = key),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 150),
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
              decoration: BoxDecoration(
                color: isSelected
                    ? const Color(0xFF52B788).withValues(alpha: 0.15)
                    : Colors.white.withValues(alpha: 0.04),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(
                  color: isSelected
                      ? const Color(0xFF52B788)
                      : Colors.white.withValues(alpha: 0.1),
                ),
              ),
              child: Text(
                label,
                style: TextStyle(
                  color: isSelected
                      ? const Color(0xFF52B788)
                      : Colors.white38,
                  fontSize: 11,
                  fontWeight:
                      isSelected ? FontWeight.w600 : FontWeight.w400,
                ),
              ),
            ),
          );
        },
      ),
    );
  }

  Widget _buildBody(BuildContext context, ParcelProvider provider,
      List<Parcel> filtered, List<Parcel> all) {
    if (provider.isLoading) {
      return const Center(
          child: CircularProgressIndicator(color: Color(0xFF52B788)));
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
              Text(provider.error!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.white54, fontSize: 14)),
              const SizedBox(height: 24),
              OutlinedButton(
                onPressed: provider.loadParcels,
                style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: Color(0xFF52B788))),
                child: const Text('Retry',
                    style: TextStyle(color: Color(0xFF52B788))),
              ),
            ],
          ),
        ),
      );
    }

    if (all.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.map_outlined, color: Colors.white24, size: 64),
            const SizedBox(height: 16),
            const Text('No fields registered yet.',
                style: TextStyle(color: Colors.white38, fontSize: 16)),
            const SizedBox(height: 8),
            Text(
              'Use the "Add Field" button on the map to get started.',
              textAlign: TextAlign.center,
              style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.25), fontSize: 13),
            ),
          ],
        ),
      );
    }

    if (filtered.isEmpty) {
      return Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.filter_list_off,
                color: Colors.white24, size: 52),
            const SizedBox(height: 16),
            const Text('No fields match the current filter.',
                style: TextStyle(color: Colors.white38, fontSize: 15)),
            const SizedBox(height: 12),
            TextButton(
              onPressed: () => setState(() {
                _healthFilter = 'ALL';
                _cropFilter = 'ALL';
              }),
              child: const Text('Clear filters',
                  style: TextStyle(color: Color(0xFF52B788))),
            ),
          ],
        ),
      );
    }

    return ListView.separated(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      itemCount: filtered.length,
      separatorBuilder: (_, __) => const SizedBox(height: 10),
      itemBuilder: (context, index) =>
          _parcelCard(context, filtered[index]),
    );
  }

  Widget _parcelCard(BuildContext context, Parcel parcel) {
    final color = _statusColor(parcel);
    final centroid = parcel.centroid;
    final isDeleting = _deletingId == parcel.id;
    final isUpdating = _updatingId == parcel.id;

    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute(builder: (_) => AnalysisScreen(parcel: parcel)),
        ),
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: parcel.hasAnomaly
                ? const Color(0xFFE76F51).withValues(alpha: 0.06)
                : Colors.white.withValues(alpha: 0.04),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(
              color: color.withValues(alpha: parcel.hasAnomaly ? 0.5 : 0.3),
              width: parcel.hasAnomaly ? 1.8 : 1.2,
            ),
          ),
          child: Row(
            children: [
              // Icon circle
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

              // Info
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      parcel.name,
                      style: const TextStyle(
                          color: Colors.white,
                          fontSize: 15,
                          fontWeight: FontWeight.w600),
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
                              fontSize: 12),
                        ),
                        const SizedBox(width: 8),
                        Container(
                            width: 4,
                            height: 4,
                            decoration: const BoxDecoration(
                                color: Colors.white24,
                                shape: BoxShape.circle)),
                        const SizedBox(width: 8),
                        Text(
                          '${parcel.areaHa.toStringAsFixed(2)} ha',
                          style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.5),
                              fontSize: 12),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    _healthChip(parcel, color),
                  ],
                ),
              ),

              // Actions
              const SizedBox(width: 4),
              if (isDeleting || isUpdating)
                SizedBox(
                  width: 36,
                  height: 36,
                  child: Center(
                    child: SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: isDeleting
                            ? const Color(0xFFE76F51)
                            : const Color(0xFF52B788),
                      ),
                    ),
                  ),
                )
              else
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (centroid != null)
                      IconButton(
                        icon: const Icon(Icons.my_location, size: 20),
                        color: Colors.white38,
                        tooltip: 'Show on map',
                        onPressed: () {
                          Navigator.of(context).pop();
                          widget.onFlyTo(centroid, 15.0);
                        },
                      ),
                    PopupMenuButton<String>(
                      icon: const Icon(Icons.more_vert,
                          color: Colors.white38, size: 20),
                      color: const Color(0xFF132233),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12)),
                      onSelected: (value) {
                        if (value == 'edit') _showEditDialog(context, parcel);
                        if (value == 'delete') _confirmDelete(context, parcel);
                      },
                      itemBuilder: (_) => [
                        const PopupMenuItem(
                          value: 'edit',
                          child: Row(children: [
                            Icon(Icons.edit_outlined,
                                color: Color(0xFF52B788), size: 18),
                            SizedBox(width: 10),
                            Text('Edit field',
                                style: TextStyle(
                                    color: Color(0xFF52B788), fontSize: 14)),
                          ]),
                        ),
                        const PopupMenuItem(
                          value: 'delete',
                          child: Row(children: [
                            Icon(Icons.delete_outline,
                                color: Color(0xFFE76F51), size: 18),
                            SizedBox(width: 10),
                            Text('Delete field',
                                style: TextStyle(
                                    color: Color(0xFFE76F51), fontSize: 14)),
                          ]),
                        ),
                      ],
                    ),
                  ],
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _healthChip(Parcel parcel, Color color) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Flexible(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              _healthLabel(parcel),
              style: TextStyle(
                  color: color, fontSize: 11, fontWeight: FontWeight.w600),
              overflow: TextOverflow.ellipsis,
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
            _statusLabel(parcel.status),
            style: const TextStyle(color: Colors.white38, fontSize: 11),
          ),
        ),
      ],
    );
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'ACTIVE':
        return 'Active';
      case 'PENDING':
        return 'Pending';
      case 'ARCHIVED':
        return 'Archived';
      default:
        return status;
    }
  }

  InputDecoration _inputDecoration(String label) {
    return InputDecoration(
      labelText: label,
      labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.2)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Color(0xFF52B788)),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: Colors.redAccent),
      ),
    );
  }
}
