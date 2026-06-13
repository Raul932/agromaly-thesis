import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../core/constants.dart';
import '../providers/parcel_provider.dart';

/// Screen for creating a new agricultural parcel.
///
/// Provides form fields for name, crop type, area, and a demo polygon.
/// Also includes a placeholder "Import APIA / GPX" button for future
/// file ingestion support.
class AddParcelScreen extends StatefulWidget {
  const AddParcelScreen({super.key});

  @override
  State<AddParcelScreen> createState() => _AddParcelScreenState();
}

class _AddParcelScreenState extends State<AddParcelScreen> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _descriptionController = TextEditingController();
  final _areaController = TextEditingController(text: '5.2');
  String _selectedCropType = 'WHEAT';
  bool _isSubmitting = false;
  String? _error;

  // Default demo polygon: A real farm field near Timișoara, Romania
  // Coordinates in [lon, lat] GeoJSON order
  static const _demoCoordinates = [
    [
      [21.2200, 45.7600],
      [21.2250, 45.7600],
      [21.2250, 45.7565],
      [21.2200, 45.7565],
      [21.2200, 45.7600], // closed ring
    ]
  ];

  @override
  void dispose() {
    _nameController.dispose();
    _descriptionController.dispose();
    _areaController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _isSubmitting = true;
      _error = null;
    });

    final success = await context.read<ParcelProvider>().addParcel(
          name: _nameController.text.trim(),
          cropType: _selectedCropType,
          areaHa: double.parse(_areaController.text.trim()),
          description: _descriptionController.text.trim().isEmpty
              ? null
              : _descriptionController.text.trim(),
          coordinates: _demoCoordinates
              .map((ring) =>
                  ring.map((coord) => coord.map((c) => c.toDouble()).toList()).toList())
              .toList(),
        );

    if (mounted) {
      setState(() => _isSubmitting = false);
      if (success) {
        Navigator.of(context).pop(true);
      } else {
        setState(() {
          _error = context.read<ParcelProvider>().error;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D1B2A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D1B2A),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.white70),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: const Text(
          'New Parcel',
          style: TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w600,
            fontSize: 18,
          ),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // --- Parcel Info Section ---
              _sectionHeader('Parcel Information', Icons.info_outline),
              const SizedBox(height: 16),

              _buildTextField(
                controller: _nameController,
                label: 'Parcel Name',
                hint: 'e.g., North Field - Wheat',
                icon: Icons.label_outline,
                validator: (v) {
                  if (v == null || v.trim().isEmpty) return 'Name is required';
                  if (v.length > 255) return 'Name too long';
                  return null;
                },
              ),
              const SizedBox(height: 16),

              _buildTextField(
                controller: _descriptionController,
                label: 'Description (optional)',
                hint: 'Notes about this field...',
                icon: Icons.notes,
                maxLines: 3,
              ),
              const SizedBox(height: 16),

              // Crop type dropdown
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.06),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: Colors.white.withValues(alpha: 0.15),
                  ),
                ),
                child: DropdownButtonFormField<String>(
                  initialValue: _selectedCropType,
                  dropdownColor: const Color(0xFF1B4332),
                  style: const TextStyle(color: Colors.white),
                  icon: const Icon(Icons.expand_more, color: Colors.white54),
                  decoration: InputDecoration(
                    labelText: 'Crop Type',
                    labelStyle:
                        TextStyle(color: Colors.white.withValues(alpha: 0.6)),
                    prefixIcon:
                        const Icon(Icons.grass, color: Colors.white54),
                    border: InputBorder.none,
                  ),
                  items: kCropTypes.map((type) {
                    return DropdownMenuItem(
                      value: type,
                      child: Text(
                        type.replaceAll('_', ' ').toUpperCase(),
                        style: const TextStyle(fontSize: 14),
                      ),
                    );
                  }).toList(),
                  onChanged: (v) {
                    if (v != null) setState(() => _selectedCropType = v);
                  },
                ),
              ),
              const SizedBox(height: 16),

              _buildTextField(
                controller: _areaController,
                label: 'Area (hectares)',
                hint: '5.2',
                icon: Icons.square_foot,
                keyboardType: TextInputType.number,
                validator: (v) {
                  if (v == null || v.trim().isEmpty) return 'Area is required';
                  final n = double.tryParse(v.trim());
                  if (n == null || n <= 0) return 'Must be a positive number';
                  return null;
                },
              ),

              const SizedBox(height: 32),

              // --- Geometry Section ---
              _sectionHeader('Parcel Geometry', Icons.map_outlined),
              const SizedBox(height: 16),

              // Import APIA/GPX placeholder
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.04),
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(
                    color: const Color(0xFF52B788).withValues(alpha: 0.2),
                    style: BorderStyle.solid,
                  ),
                ),
                child: Column(
                  children: [
                    OutlinedButton.icon(
                      onPressed: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text(
                              'APIA / GPX file import coming soon!',
                            ),
                            backgroundColor: Color(0xFF1B4332),
                          ),
                        );
                      },
                      icon: const Icon(Icons.upload_file,
                          color: Color(0xFF52B788)),
                      label: const Text(
                        'Import APIA / GPX File',
                        style: TextStyle(color: Color(0xFF52B788)),
                      ),
                      style: OutlinedButton.styleFrom(
                        side: const BorderSide(color: Color(0xFF52B788)),
                        padding: const EdgeInsets.symmetric(
                            horizontal: 24, vertical: 14),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Or using demo coordinates (Timișoara farmland)',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.5),
                        fontSize: 12,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        'Polygon: 45.756°N – 45.760°N, 21.220°E – 21.225°E\n'
                        '(≈ 5.2 ha near Timișoara, Romania)',
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.6),
                          fontFamily: 'monospace',
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 32),

              // --- Error ---
              if (_error != null)
                Container(
                  margin: const EdgeInsets.only(bottom: 16),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: Colors.red.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(
                    _error!,
                    style: const TextStyle(color: Colors.redAccent, fontSize: 13),
                  ),
                ),

              // --- Submit Button ---
              SizedBox(
                height: 52,
                child: ElevatedButton.icon(
                  onPressed: _isSubmitting ? null : _submit,
                  icon: _isSubmitting
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.check_circle, color: Colors.white),
                  label: Text(
                    _isSubmitting ? 'Creating...' : 'Create Parcel',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF52B788),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(14),
                    ),
                    elevation: 0,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _sectionHeader(String title, IconData icon) {
    return Row(
      children: [
        Icon(icon, color: const Color(0xFF52B788), size: 20),
        const SizedBox(width: 8),
        Text(
          title,
          style: const TextStyle(
            color: Colors.white,
            fontSize: 16,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }

  Widget _buildTextField({
    required TextEditingController controller,
    required String label,
    String? hint,
    required IconData icon,
    int maxLines = 1,
    TextInputType? keyboardType,
    String? Function(String?)? validator,
  }) {
    return TextFormField(
      controller: controller,
      maxLines: maxLines,
      keyboardType: keyboardType,
      style: const TextStyle(color: Colors.white),
      validator: validator,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: TextStyle(color: Colors.white.withValues(alpha: 0.6)),
        hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.3)),
        prefixIcon: Icon(icon, color: Colors.white54),
        filled: true,
        fillColor: Colors.white.withValues(alpha: 0.06),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.15)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.15)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFF52B788), width: 1.5),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Colors.redAccent),
        ),
      ),
    );
  }
}
